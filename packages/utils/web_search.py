import os
from typing import List, Dict
from tavily import TavilyClient
from .logging_config import logger

class WebSearcher:
    def __init__(self):
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable is not set")
        self.client = TavilyClient(api_key)
        logger.info("WebSearcher initialized with Tavily client")

    def search(self, query: str, max_results: int = 1) -> List[Dict]:
        """
        Use Tavily Search for relevant information

        Args:
            query: Search Query
            max_results: Maximum number of returns

        Returns:
            Search result list
        """
        try:
            search_results = self.client.search(
                query=query,
                search_depth="basic",
                max_results=max_results
            )

            # Can not open message
            formatted_results = []
            for result in search_results['results'][:max_results]:
                formatted_results.append({
                    'title': result.get('title', ''),
                    'content': result.get('content', ''),
                    'url': result.get('url', ''),
                    'score': result.get('score', 0)
                })

            return formatted_results

        except Exception as e:
            logger.error(f"Error during web search: {str(e)}")
            return []

    def format_search_results(self, results: List[Dict]) -> str:
        """
        Format search results into text

        Args:
            results: Search result list

        Returns:
            Formatted Text
        """
        if not results:
            return "No relevant web search results found。"

        formatted_text = "Here's the results of the network search.：\n\n"
        for i, result in enumerate(results, 1):
            formatted_text += f"{i}. {result['title']}\n"
            formatted_text += f"   {result['content']}\n"
            formatted_text += f"   Source: {result['url']}\n\n"

        return formatted_text