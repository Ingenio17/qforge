"""
Run Manager for tracking simulation sessions.
"""

import os
import time
import uuid
import json
import logging
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any

from qforge.config.defaults import OUTPUT_DIRS

class RunManager:
    """
    Manages simulation runs, output directories, and logging.
    """
    
    def __init__(self):
        """Initialize the RunManager."""
        self.current_run_id = None
        self.current_run_dir = None
        self.start_time = None
        self._ensure_base_dirs()
    
    def _ensure_base_dirs(self):
        """Ensure base output directories exist."""
        # Ensure 'outputs/runs' exists
        runs_dir = Path("outputs/runs")
        runs_dir.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def create_run(self, tag: Optional[str] = None, parameters: Optional[Dict[str, Any]] = None):
        """
        Start a new managed run context.
        
        Args:
            tag: Optional string tag to identify the run (e.g., "fluxonium_test")
            parameters: Optional dictionary of run parameters to save
            
        Yields:
            tuple: (run_id, run_dir_path)
        """
        try:
            self.start_run(tag, parameters)
            yield self.current_run_id, self.current_run_dir
        finally:
            self.end_run()
            
    def start_run(self, tag: Optional[str] = None, parameters: Optional[Dict[str, Any]] = None):
        """
        Start a new simulation run.
        
        Args:
            tag: Optional string tag to identify the run
            parameters: Optional dictionary of parameters to record
            
        Returns:
            str: The unique run ID
        """
        self.start_time = datetime.now()
        
        # ID Format: YYYY-MM-DD_HH-MM-SS_{tag}_{short_uuid}
        timestamp = self.start_time.strftime("%Y-%m-%d_%H-%M-%S")
        short_uuid = str(uuid.uuid4())[:8]
        
        if tag:
            # Sanitize tag
            clean_tag = "".join(c if c.isalnum() else "_" for c in tag)
            self.current_run_id = f"{timestamp}_{clean_tag}_{short_uuid}"
        else:
            self.current_run_id = f"{timestamp}_{short_uuid}"
            
        # Create directory structure
        self.current_run_dir = Path("outputs/runs") / self.current_run_id
        self.current_run_dir.mkdir(parents=True, exist_ok=True)
        
        (self.current_run_dir / "plots").mkdir(exist_ok=True)
        (self.current_run_dir / "logs").mkdir(exist_ok=True)
        (self.current_run_dir / "data").mkdir(exist_ok=True)
        
        # Setup logging
        self._setup_logging()
        
        # Create manifest
        self._create_manifest(tag, parameters)
        
        logging.info(f"Run started: {self.current_run_id}")
        return self.current_run_id

    def end_run(self):
        """Finalize the current run."""
        if self.current_run_id:
            duration = datetime.now() - self.start_time
            logging.info(f"Run completed in {duration}")
            
            # Update manifest with completion time
            manifest_path = self.current_run_dir / "run_info.json"
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r') as f:
                        data = json.load(f)
                    data["status"] = "completed"
                    data["duration_seconds"] = duration.total_seconds()
                    
                    with open(manifest_path, 'w') as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass
            
            # Clear state
            self.current_run_id = None
            self.current_run_dir = None
            
            # Reset logging to console only (or default)
            logging.getLogger().handlers = [] 

    def _setup_logging(self):
        """Configure logging to file and console."""
        log_file = self.current_run_dir / "logs" / "run.log"
        
        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ],
            force=True
        )
        
    def _create_manifest(self, tag: Optional[str], parameters: Optional[Dict]):
        """Create run_info.json containing metadata."""
        manifest = {
            "run_id": self.current_run_id,
            "timestamp": self.start_time.isoformat(),
            "tag": tag,
            "status": "running",
            "parameters": parameters or {},
            "platform": os.name
        }
        
        with open(self.current_run_dir / "run_info.json", 'w') as f:
            json.dump(manifest, f, indent=2)
            
    def get_run_dir(self) -> Path:
        """Get the current run directory."""
        if not self.current_run_dir:
            from qforge.config.defaults import OUTPUT_DIRS
            return Path(OUTPUT_DIRS["base"])
        return self.current_run_dir
