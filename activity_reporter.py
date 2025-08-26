"""
Activity Reporter Module
Reports user activity to external monitoring service
"""

import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ActivityReporter:
    """Reports user activity to external monitoring service"""
    
    def __init__(self, mongodb_uri: str, service_id: str, service_name: str):
        """
        Initialize the activity reporter
        
        Args:
            mongodb_uri: MongoDB connection URI
            service_id: Service identifier
            service_name: Service name for reporting
        """
        self.mongodb_uri = mongodb_uri
        self.service_id = service_id
        self.service_name = service_name
        self.is_connected = False
        
        # Try to connect (but don't fail if connection fails)
        try:
            # In production, this would establish actual MongoDB connection
            # For now, we'll just log the initialization
            logger.info(f"ActivityReporter initialized for service: {service_name} ({service_id})")
            self.is_connected = True
        except Exception as e:
            logger.warning(f"Failed to initialize ActivityReporter: {e}")
            self.is_connected = False
    
    def report_activity(self, user_id: int) -> bool:
        """
        Report user activity
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if activity was reported successfully, False otherwise
        """
        try:
            if not self.is_connected:
                return False
                
            # In production, this would send data to MongoDB
            # For now, we'll just log the activity
            timestamp = datetime.utcnow().isoformat()
            logger.debug(f"Activity reported - User: {user_id}, Service: {self.service_name}, Time: {timestamp}")
            
            # Here you would normally:
            # 1. Connect to MongoDB using self.mongodb_uri
            # 2. Insert activity record with user_id, service_id, timestamp
            # 3. Handle any errors gracefully
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to report activity for user {user_id}: {e}")
            return False


def create_reporter(mongodb_uri: str, service_id: str, service_name: str) -> ActivityReporter:
    """
    Factory function to create an ActivityReporter instance
    
    Args:
        mongodb_uri: MongoDB connection URI
        service_id: Service identifier
        service_name: Service name for reporting
        
    Returns:
        ActivityReporter instance
    """
    return ActivityReporter(
        mongodb_uri=mongodb_uri,
        service_id=service_id,
        service_name=service_name
    )