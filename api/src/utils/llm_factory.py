import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


def get_chat_model(model_name: str, temperature: float = 0, **kwargs):
    """
    Modular factory to switch between Google AI Studio and the local Gemini CLI Proxy.
    """
    provider = os.getenv("LLM_PROVIDER", "google").lower()

    # Sanitize kwargs for OpenAI-compatible providers
    if provider != "google":
        if "model_kwargs" in kwargs:
            model_kwargs = kwargs["model_kwargs"].copy()
            # Remove Google-specific parameters
            model_kwargs.pop("automatic_function_calling", None)
            if not model_kwargs:
                kwargs.pop("model_kwargs")
            else:
                kwargs["model_kwargs"] = model_kwargs

    if provider == "proxy":
        proxy_url = os.getenv("LLM_PROXY_URL", "http://172.17.0.1:8000/v1")
        return ChatOpenAI(
            model=model_name,
            base_url=proxy_url,
            api_key=SecretStr(os.getenv("OPENAI_API_KEY") or "none"),
            temperature=temperature,
            **kwargs,
        )
    if provider == "lmstudio":
        lm_studio_url = os.getenv("LM_STUDIO_BASE_URL", "http://192.168.88.240:1234/v1")
        return ChatOpenAI(
            model=model_name,
            base_url=lm_studio_url,
            api_key=SecretStr("not-needed"),
            temperature=temperature,
            **kwargs,
        )
    if provider == "openai":
        return ChatOpenAI(
            model=model_name,
            api_key=SecretStr(os.getenv("OPENAI_API_KEY") or "none"),
            temperature=temperature,
            **kwargs,
        )
    # For Google, we can pass through extra kwargs like automatic_function_calling
    return ChatGoogleGenerativeAI(
        model=model_name, google_api_key=os.getenv("GOOGLE_API_KEY"), temperature=temperature, **kwargs
    )
