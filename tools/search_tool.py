import os
from typing import Optional, Dict, Any
from tavily import TavilyClient, AsyncTavilyClient


class WebSearchTool:
    """
    A web search utility for health agents using the native tavily-python client.
    Supports both synchronous and asynchronous execution.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initializes the Tavily clients.

        Args:
            api_key (str, optional): The Tavily API key. If not provided, it attempts
                                     to load from the TAVILY_API_KEY environment variable.
        """
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Tavily API key is missing. Please provide it as an argument or "
                "set the TAVILY_API_KEY environment variable in your .env file."
            )

        # Initialize both clients to support sync and async workflows
        self.sync_client = TavilyClient(api_key=self.api_key)
        #self.async_client = AsyncTavilyClient(api_key=self.api_key)

    def search(self, query: str, search_depth: str = "basic", max_results: int = 5, **kwargs) -> str:
        """
        Executes a synchronous web search.

        Args:
            query (str): The search query.
            search_depth (str): "basic" or "advanced".
            max_results (int): Maximum number of results to return.
            **kwargs: Additional parameters supported by Tavily (e.g., include_domains, exclude_domains).

        Returns:
            str: The search results formatted as a string.
        """
        try:
            response = self.sync_client.search(
                query=query,
                search_depth=search_depth,
                max_results=max_results,
                **kwargs
            )
            results = response.get("results", [])
            if not results:
                return "No relevant information found."

            # 4. Format into a dense, readable Markdown string
            formatted_context = []
            for idx, res in enumerate(results, 1):
                # Example: If your Exercise Agent searches for clean bulking protocols
                title = res.get("title", "No Title")
                content = res.get("content", "No Content")
                url = res.get("url", "No URL")

                # Structure it clearly for the LLM
                chunk = f"### Source {idx}: {title}\n**URL:** {url}\n**Snippet:** {content}"
                formatted_context.append(chunk)

            # Join all chunks with a separator
            return "\n\n---\n\n".join(formatted_context)

        except Exception as e:
            print(f"Sync search failed for query '{query}': {e}")
            return f"Search failed: {str(e)}"

    # async def asearch(self, query: str, search_depth: str = "basic", max_results: int = 5, **kwargs) -> Dict[str, Any]:
    #     """
    #     Executes an asynchronous web search. Ideal for your async agentic loops.
    #
    #     Args:
    #         query (str): The search query.
    #         search_depth (str): "basic" or "advanced".
    #         max_results (int): Maximum number of results to return.
    #         **kwargs: Additional parameters supported by Tavily.
    #
    #     Returns:
    #         Dict[str, Any]: The search results.
    #     """
    #     try:
    #         response = await self.async_client.search(
    #             query=query,
    #             search_depth=search_depth,
    #             max_results=max_results,
    #             **kwargs
    #         )
    #         return response
    #     except Exception as e:
    #         # Integrate with your utils/logger.py in production
    #         print(f"Async search failed for query '{query}': {e}")
    #         return {"error": str(e), "results": []}