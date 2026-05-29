"""
Upload Processor for GrowMate Pods.

Continuous async task that processes the upload queue.
Handles both sensor data and camera image uploads.

Data Queue - Offline Operation
- Decouple data collection from upload
- Process queue items in FIFO order
- Retry failed uploads
- Rate limiting to avoid overwhelming server
"""

import asyncio
import logging
from typing import Optional
from queue_manager import QueueManager
from api_client import APIClient


logger = logging.getLogger("growmate.upload_processor")


class UploadProcessor:
    """Processes upload queue continuously."""
    
    def __init__(self, queue_manager: QueueManager, api_client: APIClient, config: dict):
        """
        Initialize upload processor.
        
        Args:
            queue_manager: Queue manager instance
            api_client: API client instance
            config: Configuration dictionary
        """
        self.queue = queue_manager
        self.api_client = api_client
        self.config = config
        
        # Rate limiting settings
        self.max_concurrent_uploads = 3  # Max parallel uploads
        self.upload_delay = 0.5  # Delay between uploads (seconds)
        
        # Statistics
        self.stats = {
            'sensor_uploads_success': 0,
            'sensor_uploads_failed': 0,
            'image_uploads_success': 0,
            'image_uploads_failed': 0,
            'total_processed': 0
        }
        
        # Semaphore for rate limiting
        self.upload_semaphore = asyncio.Semaphore(self.max_concurrent_uploads)
    
    async def process_sensor_item(self, item: dict) -> bool:
        """
        Process a single sensor data item from queue.
        
        Args:
            item: Queue item dictionary
            
        Returns:
            True if upload successful, False otherwise
        """
        try:
            # Extract data
            device_id = item['device_id']
            firmware_version = item['firmware_version']
            sensor_data = item['sensor_data']
            current_state = item['current_state']
            retry_count = item['retry_count']
            item_id = item['id']
            
            logger.debug(
                f"Processing sensor data: ID {item_id}, "
                f"retry {retry_count}, {len(sensor_data)} sensors"
            )
            
            # Upload to API
            commands = await self.api_client.upload_sensor_data(sensor_data, current_state)
            
            if commands is not None:
                # Success
                await self.queue.async_mark_sensor_uploaded(item_id)
                self.stats['sensor_uploads_success'] += 1
                self.stats['total_processed'] += 1
                
                logger.info(f"Sensor data uploaded successfully: ID {item_id}")
                
                # Note: Commands are returned but not processed here
                # They will be processed in the next sensor reading cycle
                # This is acceptable as commands are typically not time-critical
                
                return True
            else:
                # Failed
                await self.queue.async_mark_sensor_failed(item_id)
                self.stats['sensor_uploads_failed'] += 1
                self.stats['total_processed'] += 1
                
                logger.warning(f"Sensor data upload failed: ID {item_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing sensor item: {e}")
            # Mark as failed
            try:
                await self.queue.async_mark_sensor_failed(item['id'])
            except:
                pass
            return False
    
    async def process_image_item(self, item: dict) -> bool:
        """
        Process a single image item from queue.
        
        Args:
            item: Queue item dictionary
            
        Returns:
            True if upload successful, False otherwise
        """
        try:
            # Extract data
            device_id = item['device_id']
            image_data = item['image_data']
            image_size = item['image_size']
            retry_count = item['retry_count']
            item_id = item['id']
            
            logger.debug(
                f"Processing image: ID {item_id}, "
                f"retry {retry_count}, {image_size} bytes"
            )
            
            # Upload to API
            success = await self.api_client.upload_camera_image(image_data)
            
            if success:
                # Success
                await self.queue.async_mark_image_uploaded(item_id)
                self.stats['image_uploads_success'] += 1
                self.stats['total_processed'] += 1
                
                logger.info(f"Image uploaded successfully: ID {item_id}")
                return True
            else:
                # Failed
                await self.queue.async_mark_image_failed(item_id)
                self.stats['image_uploads_failed'] += 1
                self.stats['total_processed'] += 1
                
                logger.warning(f"Image upload failed: ID {item_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing image item: {e}")
            # Mark as failed
            try:
                await self.queue.async_mark_image_failed(item['id'])
            except:
                pass
            return False
    
    async def process_queue_once(self) -> int:
        """
        Process queue once (one sensor item and one image item).
        
        Returns:
            Number of items processed
        """
        processed = 0
        
        # Process sensor data (if available)
        sensor_item = await self.queue.async_dequeue_next_sensor()
        if sensor_item:
            async with self.upload_semaphore:
                await self.process_sensor_item(sensor_item)
                processed += 1
                await asyncio.sleep(self.upload_delay)
        
        # Process image (if available)
        image_item = await self.queue.async_dequeue_next_image()
        if image_item:
            async with self.upload_semaphore:
                await self.process_image_item(image_item)
                processed += 1
                await asyncio.sleep(self.upload_delay)
        
        return processed
    
    async def run_continuous(self, shutdown_event: asyncio.Event):
        """
        Run upload processor continuously until shutdown.
        
        This is the main loop that processes the queue.
        
        Args:
            shutdown_event: Event to signal shutdown
        """
        logger.info("Upload processor started")
        
        try:
            while not shutdown_event.is_set():
                try:
                    # Process queue
                    processed = await self.process_queue_once()
                    
                    if processed == 0:
                        # Queue empty, wait a bit before checking again
                        await asyncio.sleep(2.0)
                    else:
                        # Items processed, check queue again immediately
                        await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error in upload processor loop: {e}")
                    await asyncio.sleep(5.0)  # Wait before retrying
            
            logger.info("Upload processor stopped")
            
        except asyncio.CancelledError:
            logger.info("Upload processor cancelled")
            raise
    
    def get_stats(self) -> dict:
        """
        Get upload processor statistics.
        
        Returns:
            Dictionary with statistics
        """
        return self.stats.copy()
    
    def reset_stats(self):
        """Reset statistics counters."""
        self.stats = {
            'sensor_uploads_success': 0,
            'sensor_uploads_failed': 0,
            'image_uploads_success': 0,
            'image_uploads_failed': 0,
            'total_processed': 0
        }


async def run_upload_processor(
    queue_manager: QueueManager,
    api_client: APIClient,
    config: dict,
    shutdown_event: asyncio.Event
):
    """
    Convenience function to run upload processor.
    
    Args:
        queue_manager: Queue manager instance
        api_client: API client instance
        config: Configuration dictionary
        shutdown_event: Event to signal shutdown
    """
    processor = UploadProcessor(queue_manager, api_client, config)
    await processor.run_continuous(shutdown_event)
