import asyncio
import pytest
import sys
import os
import time

# Add root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.utils.coroutine_pool import CoroutinePool

@pytest.fixture
def coroutine_pool():
    """Example of creating a coroutine pool"""
    return CoroutinePool(max_workers=5)

async def dummy_task(duration, return_value=None, raise_error=False):
    """Virtual task for testing"""
    await asyncio.sleep(duration)
    if raise_error:
        raise ValueError("Test error")
    return return_value or duration

@pytest.mark.asyncio
async def test_submit_task(coroutine_pool):
    """Test task submission"""
    # Commit Task
    result = await coroutine_pool.submit(dummy_task(0.1, "Test Results"))
    
    # Verify Results
    assert result == "Test Results"

@pytest.mark.asyncio
async def test_concurrent_tasks(coroutine_pool):
    """Test concurrent execution"""
    # Multiple tasks submitted
    start_time = time.time()
    tasks = [
        coroutine_pool.submit(dummy_task(0.5, i))
        for i in range(10)
    ]
    
    # Waiting for all tasks to be completed
    results = await asyncio.gather(*tasks)
    end_time = time.time()
    
    # Authentication Results
    assert results == list(range(10))
    
    # Validation and execution (total time should be less than the time of serial execution)
    # 5 workshops, 0.5 seconds each, should take about one second to complete.
    assert end_time - start_time < 2.0  # Add some surplus

@pytest.mark.asyncio
async def test_cancel_task(coroutine_pool):
    """Test Cancel"""
    # Submit long running tasks
    async def long_task():
        try:
            await asyncio.sleep(10)
            return "Completed"
        except asyncio.CancelledError:
            return "Canceled"
    
    task_id = "test_task"
    task = asyncio.create_task(coroutine_pool.submit(long_task(), task_id=task_id))
    
    # Wait a little while to make sure the mission starts.
    await asyncio.sleep(0.1)
    
    # Cancel Task
    result = await coroutine_pool.cancel_task(task_id)
    assert result is True
    
    # Authentication tasks removed from the pool
    assert task_id not in coroutine_pool.tasks

@pytest.mark.asyncio
async def test_error_handling(coroutine_pool):
    """Test error processing"""
    # Submission of an error
    with pytest.raises(ValueError, match="Test error"):
        await coroutine_pool.submit(dummy_task(0.1, raise_error=True))
    
    # Authentication tasks removed from the pool
    assert len(coroutine_pool.tasks) == 0

if __name__ == "__main__":
    asyncio.run(pytest.main(["-xvs", __file__]))