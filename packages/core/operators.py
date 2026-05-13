"""
It's stored here. RAG Some relevant components
"""

from ..utils import prompts

class BaseOperator:
    """
    Base Category
    """
    template = None

    def __init__(self):
        pass

    def call(self, **kwargs):
        pass

    def __call__(self, **kwargs):
        """
        All RAG Call interface for relevant components
        """
        return self.call(**kwargs)



class HyDEOperator(BaseOperator):
    """
    HyDE Rewrite queries
    """
    template = prompts.HYDE_PROMPT_TEMPLATE

    def __init__(self):
        super().__init__()

    @classmethod
    def call(cls, model_callable, query, context_str, **kwargs):
        """
        Rewrite queries

        Args:
            model_callable: Model Call Functions
            query: Question
            context_str: Context
        """
        prompt = cls.template.format(query=query, context_str=context_str)
        response = model_callable(prompt)
        return response
