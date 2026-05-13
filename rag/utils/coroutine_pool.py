import asyncio
from typing import Callable, Dict, Any, Coroutine, TypeVar, Optional, List
import functools
import time

T = TypeVar('T')

class CoroutinePool:
    """Collapse Pool Manager，To limit the number of co-ordination processes"""
    
    def __init__(self, max_workers: int = 10):
        """Initializing Concord pool
        
        Args:
            max_workers: Maximum number of jobs
        """
        self.semaphore = asyncio.Semaphore(max_workers)
        self.tasks: Dict[str, asyncio.Task] = {}
        self._cleanup_lock = asyncio.Lock()
        
    async def submit(self, coro: Coroutine[Any, Any, T], task_id: Optional[str] = None) -> T:
        """Submit the process to the pool for execution
        
        Args:
            coro: Process to be implemented
            task_id: TasksID，If forNoneAuto Generate
            
        Returns:
            Process implementation results
        """
        async with self.semaphore:
            if task_id is None:
                task_id = f"task_{id(coro)}_{time.time()}"
                
            task = asyncio.create_task(coro)
            self.tasks[task_id] = task
            
            try:
                result = await task
                return result
            finally:
                # Clean up after mission
                async with self._cleanup_lock:
                    if task_id in self.tasks:
                        del self.tasks[task_id]
    
    def get_running_tasks(self) -> List[str]:
        """Get running jobsIDList"""
        return list(self.tasks.keys())
    
    async def cancel_task(self, task_id: str) -> bool:
        """Other Organiser
        
        Args:
            task_id: TasksID
            
        Returns:
            Successful Cancel
        """
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            async with self._cleanup_lock:
                if task_id in self.tasks:
                    del self.tasks[task_id]
            return True
        return False
    
    async def wait_all(self):
        """Waiting for all tasks to be completed"""
        if not self.tasks:
            return
            
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)