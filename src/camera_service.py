"""
Camera service for GrowMate Pods.

Handles Pi Camera Module v1 image capture and JPEG encoding.
"""

import logging
import io
from typing import Optional
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput


logger = logging.getLogger("growmate.camera")


# Camera configuration (matches ESP32 exactly: SVGA resolution, JPEG quality 12)
# ESP32 uses FRAMESIZE_SVGA (800x600) with JPEG quality 12 (ESP32 scale: 0=best, 63=worst)
# Standard JPEG quality ~80-85 approximates ESP32 quality 12
CAMERA_WIDTH = 800
CAMERA_HEIGHT = 600
JPEG_QUALITY = 85  # 0-100 scale (higher = better quality)


class CameraService:
    """Manages Pi Camera Module v1 for image capture."""
    
    def __init__(self):
        """Initialize camera service."""
        self.camera: Optional[Picamera2] = None
        self.initialized = False
    
    def initialize(self) -> bool:
        """
        Initialize Pi Camera.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.camera = Picamera2()
            
            # Configure camera for still capture
            config = self.camera.create_still_configuration(
                main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT)},
                buffer_count=1
            )
            self.camera.configure(config)
            
            self.camera.start()
            self.initialized = True
            
            logger.info(f"Camera initialized: {CAMERA_WIDTH}x{CAMERA_HEIGHT}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            self.initialized = False
            return False
    
    def capture_jpeg(self) -> Optional[bytes]:
        """
        Capture image and return JPEG bytes.
        
        Returns:
            JPEG image bytes or None on failure
        """
        if not self.initialized:
            if not self.initialize():
                return None
        
        try:
            # Capture to memory buffer
            stream = io.BytesIO()
            self.camera.capture_file(stream, format='jpeg')
            
            jpeg_bytes = stream.getvalue()
            logger.info(f"Captured image: {len(jpeg_bytes)} bytes")
            
            return jpeg_bytes
            
        except Exception as e:
            logger.error(f"Failed to capture image: {e}")
            return None
    
    def capture_to_file(self, filepath: str) -> bool:
        """
        Capture image and save to file.
        
        Args:
            filepath: Path to save JPEG file
            
        Returns:
            True if successful, False otherwise
        """
        if not self.initialized:
            if not self.initialize():
                return False
        
        try:
            self.camera.capture_file(filepath, format='jpeg')
            logger.info(f"Saved image to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            return False
    
    def cleanup(self):
        """Clean up camera resources."""
        if self.camera:
            try:
                self.camera.stop()
                self.camera.close()
                logger.info("Camera cleanup complete")
            except Exception as e:
                logger.warning(f"Camera cleanup error: {e}")
            finally:
                self.camera = None
                self.initialized = False
    
    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()


# Convenience functions
def capture_image() -> Optional[bytes]:
    """
    Capture image and return JPEG bytes.
    
    Returns:
        JPEG image bytes or None on failure
    """
    with CameraService() as camera:
        return camera.capture_jpeg()


def capture_image_to_file(filepath: str) -> bool:
    """
    Capture image and save to file.
    
    Args:
        filepath: Path to save JPEG file
        
    Returns:
        True if successful, False otherwise
    """
    with CameraService() as camera:
        return camera.capture_to_file(filepath)
