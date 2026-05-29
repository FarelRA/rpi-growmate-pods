"""
Configuration file watcher using watchdog.

Monitors config file for changes and triggers hot-reload.
Debounces rapid changes to avoid excessive reloads.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


logger = logging.getLogger("growmate.config_watcher")


class ConfigFileHandler(FileSystemEventHandler):
    """
    File system event handler for config file changes.
    
    Debounces rapid changes by waiting for a quiet period before triggering callback.
    """
    
    def __init__(self, config_path: Path, callback: Callable, debounce_seconds: float = 1.0):
        """
        Initialize config file handler.
        
        Args:
            config_path: Path to config file to monitor
            callback: Callback function to call on config change
            debounce_seconds: Seconds to wait after last change before triggering callback
        """
        super().__init__()
        self.config_path = config_path.resolve()
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        self.last_modified = 0.0
        self.debounce_task: Optional[asyncio.Task] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        
    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the asyncio event loop for callback execution."""
        self.loop = loop
    
    def on_modified(self, event):
        """Handle file modification event."""
        if event.is_directory:
            return
        
        # Check if this is our config file
        event_path = Path(event.src_path).resolve()
        if event_path != self.config_path:
            return
        
        logger.debug(f"Config file modified: {event.src_path}")
        self._schedule_reload()
    
    def on_created(self, event):
        """Handle file creation event."""
        if event.is_directory:
            return
        
        # Check if this is our config file
        event_path = Path(event.src_path).resolve()
        if event_path != self.config_path:
            return
        
        logger.debug(f"Config file created: {event.src_path}")
        self._schedule_reload()
    
    def _schedule_reload(self):
        """Schedule a debounced reload."""
        current_time = time.time()
        
        # Update last modified time
        self.last_modified = current_time
        
        # Cancel existing debounce task if any
        if self.debounce_task and not self.debounce_task.done():
            self.debounce_task.cancel()
        
        # Schedule new debounce task
        if self.loop and self.loop.is_running():
            self.debounce_task = asyncio.run_coroutine_threadsafe(
                self._debounced_reload(),
                self.loop
            )
    
    async def _debounced_reload(self):
        """Wait for quiet period, then trigger reload."""
        try:
            # Wait for debounce period
            await asyncio.sleep(self.debounce_seconds)
            
            # Check if another modification happened during debounce
            time_since_last_mod = time.time() - self.last_modified
            if time_since_last_mod < self.debounce_seconds:
                # Another modification happened, reschedule
                logger.debug("Config file modified again during debounce, rescheduling")
                return
            
            # Trigger callback
            logger.info(f"Config file changed, triggering reload (debounced {self.debounce_seconds}s)")
            
            # Call callback (may be sync or async)
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback()
            else:
                self.callback()
                
        except asyncio.CancelledError:
            logger.debug("Debounce task cancelled")
        except Exception as e:
            logger.error(f"Error in config reload callback: {e}", exc_info=True)


class ConfigWatcher:
    """
    Watches configuration file for changes and triggers hot-reload.
    
    Uses watchdog library to monitor file system events.
    Debounces rapid changes to avoid excessive reloads.
    """
    
    def __init__(
        self,
        config_path: Path,
        callback: Callable,
        debounce_seconds: float = 1.0
    ):
        """
        Initialize config watcher.
        
        Args:
            config_path: Path to config file to monitor
            callback: Callback function to call on config change (sync or async)
            debounce_seconds: Seconds to wait after last change before triggering callback
        """
        self.config_path = config_path
        self.callback = callback
        self.debounce_seconds = debounce_seconds
        
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[ConfigFileHandler] = None
        self.running = False
        
    def start(self, loop: asyncio.AbstractEventLoop):
        """
        Start watching config file.
        
        Args:
            loop: Asyncio event loop for callback execution
        """
        if self.running:
            logger.warning("Config watcher already running")
            return
        
        # Create event handler
        self.event_handler = ConfigFileHandler(
            self.config_path,
            self.callback,
            self.debounce_seconds
        )
        self.event_handler.set_event_loop(loop)
        
        # Create observer
        self.observer = Observer()
        
        # Watch the directory containing the config file
        watch_dir = self.config_path.parent
        self.observer.schedule(self.event_handler, str(watch_dir), recursive=False)
        
        # Start observer
        self.observer.start()
        self.running = True
        
        logger.info(
            f"Config watcher started: monitoring {self.config_path} "
            f"(debounce: {self.debounce_seconds}s)"
        )
    
    def stop(self):
        """Stop watching config file."""
        if not self.running:
            return
        
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5.0)
            self.observer = None
        
        self.event_handler = None
        self.running = False
        
        logger.info("Config watcher stopped")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()


async def watch_config_file(
    config_path: Path,
    callback: Callable,
    debounce_seconds: float = 1.0,
    shutdown_event: Optional[asyncio.Event] = None
):
    """
    Watch config file for changes (async context).
    
    Args:
        config_path: Path to config file to monitor
        callback: Callback function to call on config change (sync or async)
        debounce_seconds: Seconds to wait after last change before triggering callback
        shutdown_event: Event to signal shutdown
    """
    watcher = ConfigWatcher(config_path, callback, debounce_seconds)
    
    try:
        # Start watcher
        loop = asyncio.get_running_loop()
        watcher.start(loop)
        
        # Wait for shutdown signal
        if shutdown_event:
            await shutdown_event.wait()
        else:
            # Wait indefinitely
            await asyncio.Event().wait()
            
    finally:
        # Stop watcher
        watcher.stop()
