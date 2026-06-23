import os
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.utils.llm_factory import get_chat_model


def test_lmstudio():
    os.environ["LLM_PROVIDER"] = "lmstudio"
    # Use one of the models discovered via curl
    model_name = os.getenv("LM_STUDIO_MODEL", "google/gemma-4-12b")

    print(f"Testing LM Studio with model: {model_name}")
    try:
        llm = get_chat_model(model_name=model_name)
        response = llm.invoke("Say hello!")
        print(f"Response: {response.content}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_lmstudio()
