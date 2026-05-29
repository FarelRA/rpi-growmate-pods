"""
Camera service for GrowMate Pods.

Handles Pi Camera Module v1 image capture and JPEG encoding.

Added async wrapper methods to avoid blocking the event loop.
Converted to persistent service with 5MP support, configurable quality, and EXIF metadata.
"""

import logging
import io
import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput

try:
    import piexif
    EXIF_AVAILABLE = True
except ImportError:
    EXIF_AVAILABLE = False
    logging.warning("piexif not available, EXIF metadata will not be added")


logger = logging.getLogger("growmate.camera")


# Default camera configuration (Full 5MP for Pi Camera v1)
DEFAULT_CAMERA_WIDTH = 2592
DEFAULT_CAMERA_HEIGHT = 1944
DEFAULT_JPEG_QUALITY = 85  # 0-100 scale (higher = better quality)


class CameraService:
    """
    Manages Pi Camera Module v1 for image capture.
    
    Persistent service - initialized once at startup, kept alive throughout
    application lifetime. Supports full 5MP resolution, configurable quality, and EXIF metadata.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize camera service.
        
        Args:
            config: Configuration dictionary with camera settings
        """
        self.config = config or {}
        self.camera: Optional[Picamera2] = None
        self.initialized = False
        self.capture_count = 0
        self.last_capture_time = None
        
        # Get camera settings from config
        camera_config = self.config.get('camera', {})
        self.width = camera_config.get('width', DEFAULT_CAMERA_WIDTH)
        self.height = camera_config.get('height', DEFAULT_CAMERA_HEIGHT)
        self.quality = camera_config.get('quality', DEFAULT_JPEG_QUALITY)
        self.add_exif = camera_config.get('add_exif', True)
        
        # Validate settings
        self.quality = max(50, min(100, self.quality))  # Clamp to 50-100
        
        logger.info(
            f"Camera service created: {self.width}x{self.height}, "
            f"quality={self.quality}, EXIF={self.add_exif}"
        )
    
    def update_config(self, new_camera_config: Dict) -> bool:
        """
        Update camera configuration at runtime (Hot-reload support).
        
        Note: Resolution changes require camera reinitialization.
        Quality changes can be applied immediately.
        
        Args:
            new_camera_config: New camera configuration dictionary
            
        Returns:
            True if successful, False otherwise
        """
        try:
            old_width = self.width
            old_height = self.height
            old_quality = self.quality
            
            # Update configuration
            self.width = new_camera_config.get('width', DEFAULT_CAMERA_WIDTH)
            self.height = new_camera_config.get('height', DEFAULT_CAMERA_HEIGHT)
            self.quality = new_camera_config.get('quality', DEFAULT_JPEG_QUALITY)
            self.quality = max(50, min(100, self.quality))  # Clamp to 50-100
            
            # Check if resolution changed (requires reinitialization)
            resolution_changed = (self.width != old_width or self.height != old_height)
            
            if resolution_changed:
                logger.info(f"Camera resolution changed: {old_width}x{old_height} → {self.width}x{self.height}")
                logger.info("Reinitializing camera with new resolution...")
                
                # Cleanup old camera
                if self.initialized:
                    self.cleanup()
                
                # Reinitialize with new resolution
                if not self.initialize():
                    logger.error("Failed to reinitialize camera with new resolution")
                    # Try to restore old settings
                    self.width = old_width
                    self.height = old_height
                    self.initialize()
                    return False
                
                logger.info("Camera reinitialized successfully with new resolution")
            
            # Quality changes don't require reinitialization
            if self.quality != old_quality:
                logger.info(f"Camera quality changed: {old_quality} → {self.quality}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update camera config: {e}")
            return False
    
    async def async_update_config(self, new_camera_config: Dict) -> bool:
        """Async wrapper for update_config()."""
        return await asyncio.to_thread(self.update_config, new_camera_config)
    
    def initialize(self) -> bool:
        """
        Initialize Pi Camera (Persistent service).
        
        Called once at startup. Camera remains active throughout application lifetime.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Initializing camera: {self.width}x{self.height}, quality={self.quality}")
            
            self.camera = Picamera2()
            
            # Configure camera for still capture with configurable resolution
            # Use full 5MP (2592x1944) by default, configurable
            # buffer_count=2 for double buffering (better performance)
            config = self.camera.create_still_configuration(
                main={"size": (self.width, self.height)},
                buffer_count=2  # Double buffering for better performance
            )
            self.camera.configure(config)
            
            self.camera.start()
            self.initialized = True
            
            logger.info(
                f"Camera initialized successfully: {self.width}x{self.height}, "
                f"quality={self.quality}, EXIF={self.add_exif}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            self.initialized = False
            return False
    
    def _reinitialize(self) -> bool:
        """
        Reinitialize camera after error (Error recovery).
        
        Returns:
            True if successful, False otherwise
        """
        logger.warning("Attempting to reinitialize camera after error")
        
        # Cleanup existing camera
        if self.camera:
            try:
                self.camera.stop()
                self.camera.close()
            except:
                pass
            self.camera = None
            self.initialized = False
        
        # Wait a bit before reinitializing
        time.sleep(1)
        
        # Reinitialize
        return self.initialize()
    
    def _add_exif_metadata(self, jpeg_bytes: bytes, sensor_data: Optional[Dict[str, Any]] = None) -> bytes:
        """
        Add EXIF metadata to JPEG image (Metadata support).
        
        Args:
            jpeg_bytes: Original JPEG bytes
            sensor_data: Optional sensor readings to include in metadata
            
        Returns:
            JPEG bytes with EXIF metadata
        """
        if not EXIF_AVAILABLE:
            return jpeg_bytes
        
        try:
            # Load existing EXIF data (if any)
            try:
                exif_dict = piexif.load(jpeg_bytes)
            except:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            # Add timestamp
            timestamp = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
            exif_dict["0th"][piexif.ImageIFD.DateTime] = timestamp
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = timestamp
            exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = timestamp
            
            # Add device ID
            device_id = self.config.get('device', {}).get('id', 'unknown')
            exif_dict["0th"][piexif.ImageIFD.Make] = "GrowMate"
            exif_dict["0th"][piexif.ImageIFD.Model] = device_id
            
            # Add image description with sensor data (if provided)
            if sensor_data:
                description = f"GrowMate capture #{self.capture_count}"
                if 'temperature' in sensor_data:
                    description += f" | Temp: {sensor_data['temperature']}C"
                if 'humidity' in sensor_data:
                    description += f" | Humidity: {sensor_data['humidity']}%"
                exif_dict["0th"][piexif.ImageIFD.ImageDescription] = description
            
            # Add software version
            firmware_version = self.config.get('firmware_version', '2.0.0')
            exif_dict["0th"][piexif.ImageIFD.Software] = f"GrowMate RPI v{firmware_version}"
            
            # Dump EXIF data and insert into JPEG
            exif_bytes = piexif.dump(exif_dict)
            jpeg_with_exif = piexif.insert(exif_bytes, jpeg_bytes)
            
            logger.debug(f"Added EXIF metadata to image")
            return jpeg_with_exif
            
        except Exception as e:
            logger.warning(f"Failed to add EXIF metadata: {e}")
            return jpeg_bytes
    
    def capture_jpeg(self, sensor_data: Optional[Dict[str, Any]] = None) -> Optional[bytes]:
        """
        Capture image and return JPEG bytes (Persistent service with EXIF).
        
        Args:
            sensor_data: Optional sensor readings to include in EXIF metadata
        
        Returns:
            JPEG image bytes or None on failure
        """
        if not self.initialized:
            logger.warning("Camera not initialized, attempting to initialize")
            if not self.initialize():
                return None
        
        try:
            start_time = time.time()
            
            # Capture to memory buffer
            stream = io.BytesIO()
            self.camera.capture_file(stream, format='jpeg')
            
            jpeg_bytes = stream.getvalue()
            capture_time = time.time() - start_time
            
            # Add EXIF metadata if enabled
            if self.add_exif:
                jpeg_bytes = self._add_exif_metadata(jpeg_bytes, sensor_data)
            
            # Update statistics
            self.capture_count += 1
            self.last_capture_time = time.time()
            
            logger.info(
                f"Captured image #{self.capture_count}: {len(jpeg_bytes)} bytes "
                f"({len(jpeg_bytes) / 1024 / 1024:.2f} MB) in {capture_time:.2f}s"
            )
            
            return jpeg_bytes
            
        except Exception as e:
            logger.error(f"Failed to capture image: {e}")
            
            # Attempt to recover by reinitializing camera
            if self._reinitialize():
                logger.info("Camera reinitialized successfully, retrying capture")
                try:
                    stream = io.BytesIO()
                    self.camera.capture_file(stream, format='jpeg')
                    jpeg_bytes = stream.getvalue()
                    
                    if self.add_exif:
                        jpeg_bytes = self._add_exif_metadata(jpeg_bytes, sensor_data)
                    
                    self.capture_count += 1
                    self.last_capture_time = time.time()
                    
                    logger.info(f"Retry successful: {len(jpeg_bytes)} bytes")
                    return jpeg_bytes
                except Exception as retry_error:
                    logger.error(f"Retry failed: {retry_error}")
            
            return None
    
    def capture_to_file(self, filepath: str, sensor_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Capture image and save to file (With EXIF support).
        
        Args:
            filepath: Path to save JPEG file
            sensor_data: Optional sensor readings to include in EXIF metadata
            
        Returns:
            True if successful, False otherwise
        """
        # Capture to memory first (to add EXIF)
        jpeg_bytes = self.capture_jpeg(sensor_data)
        
        if not jpeg_bytes:
            return False
        
        try:
            with open(filepath, 'wb') as f:
                f.write(jpeg_bytes)
            logger.info(f"Saved image to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save image to file: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get camera statistics (Monitoring).
        
        Returns:
            Dictionary with camera statistics
        """
        return {
            'initialized': self.initialized,
            'capture_count': self.capture_count,
            'last_capture_time': self.last_capture_time,
            'resolution': f"{self.width}x{self.height}",
            'quality': self.quality,
            'exif_enabled': self.add_exif
        }
    
    def cleanup(self):
        """
        Clean up camera resources (Called only on shutdown).
        
        This is called only when the application shuts down,
        not after every capture.
        """
        if self.camera:
            try:
                self.camera.stop()
                self.camera.close()
                logger.info(
                    f"Camera cleanup complete. Total captures: {self.capture_count}"
                )
            except Exception as e:
                logger.warning(f"Camera cleanup error: {e}")
            finally:
                self.camera = None
                self.initialized = False
    
    async def async_cleanup(self):
        """Async wrapper for cleanup."""
        await asyncio.to_thread(self.cleanup)
    
    def __enter__(self):
        """Context manager entry (deprecated)."""
        logger.warning("Context manager usage is deprecated, use persistent service")
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit (deprecated)."""
        self.cleanup()
    
    # Async wrapper methods 
    
    async def async_initialize(self) -> bool:
        """
        Async wrapper for initialize().
        
        Returns:
            True if successful, False otherwise
        """
        return await asyncio.to_thread(self.initialize)
    
    async def async_capture_jpeg(self, sensor_data: Optional[Dict[str, Any]] = None) -> Optional[bytes]:
        """
        Async wrapper for capture_jpeg() (With sensor data).
        
        Runs blocking camera operations in a thread pool to avoid blocking the event loop.
        This is the RPI-optimized approach for async architecture.
        
        Args:
            sensor_data: Optional sensor readings to include in EXIF metadata
        
        Returns:
            JPEG image bytes or None on failure
        """
        return await asyncio.to_thread(self.capture_jpeg, sensor_data)
    
    async def async_capture_to_file(self, filepath: str, sensor_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Async wrapper for capture_to_file() (With sensor data).
        
        Runs blocking camera operations in a thread pool to avoid blocking the event loop.
        
        Args:
            filepath: Path to save JPEG file
            sensor_data: Optional sensor readings to include in EXIF metadata
            
        Returns:
            True if successful, False otherwise
        """
        return await asyncio.to_thread(self.capture_to_file, filepath, sensor_data)


# Note: Convenience functions removed
# Camera should be initialized once and kept alive as a persistent service
# Use CameraService directly with initialize() at startup and cleanup() at shutdown
