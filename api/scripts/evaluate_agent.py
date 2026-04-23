import sys
import os
import base64
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load and decode API Key
load_dotenv(Path(__file__).parent.parent / ".env")
api_key_raw = os.getenv("GOOGLE_API_KEY")
if api_key_raw:
    try:
        decoded_bytes = base64.b64decode(api_key_raw, validate=True)
        decoded_str = decoded_bytes.decode("utf-8")
        if decoded_str.startswith("AIza"):
            os.environ["GOOGLE_API_KEY"] = decoded_str
    except Exception:
        pass

from src.agent.graph import graph

async def run_evaluation():
    print("🧪 Starting Ragas Evaluation...")
    
    # 1. Load Dataset
    dataset_path = Path(__file__).parent.parent / "tests" / "eval_dataset.json"
    with open(dataset_path, "r") as f:
        test_samples = json.load(f)

    evaluation_data = {
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": []
    }

    # 2. Generate Answers and Collect Contexts
    for sample in test_samples:
        question = sample["question"]
        print(f"🤔 Querying: {question}")
        
        inputs = {"messages": [HumanMessage(content=question)]}
        
        # Invoke Agent
        result = await graph.ainvoke(inputs)
        
        # Extract Answer
        answer = result["messages"][-1].content
        if isinstance(answer, list):
            answer = "\n".join([t.get("text", "") for t in answer if isinstance(t, dict) and "text" in t])
        
        # Extract Context (from ToolMessages)
        contexts = []
        for msg in result["messages"]:
            if isinstance(msg, ToolMessage):
                contexts.append(msg.content)
        
        evaluation_data["question"].append(question)
        evaluation_data["answer"].append(answer)
        evaluation_data["contexts"].append(contexts)
        evaluation_data["ground_truth"].append(sample["ground_truth"])

    # 3. Setup Ragas with Gemini
    # We use Gemini 2.5 Flash as the evaluator to stay in free tier
    evaluator_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

    # Convert to HuggingFace Dataset
    dataset = Dataset.from_dict(evaluation_data)

    # 4. Perform Evaluation
    print("📊 Running Ragas metrics (this may take a minute)...")
    result = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_precision],
        llm=evaluator_llm,
        embeddings=embeddings
    )

    print("\n✅ EVALUATION COMPLETE!")
    print("-" * 30)
    print(result)
    
    # Save results
    output_path = Path(__file__).parent.parent / "eval_results.json"
    with open(output_path, "w") as f:
        # Convert EvaluationResult to dict
        serializable_result = {k: v for k, v in result.items()}
        json.dump(serializable_result, f, indent=2)
    print(f"\n📁 Detailed results saved to {output_path}")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
