"""Test script for memory system improvements."""

from src.agents.memory.prompt import format_memory_for_injection


def test_fact_ranking():
    print("Testing Similarity-Based Fact Retrieval...")
    
    memory_data = {
        "user": {
            "workContext": {"summary": "Senior Software Engineer at ByteDance"},
        },
        "facts": [
            {"content": "User prefers Python for backend development", "confidence": 0.9},
            {"content": "User is learning React and Next.js", "confidence": 0.8},
            {"content": "User has a cat named Luna", "confidence": 1.0},
            {"content": "User uses Docker for all deployments", "confidence": 0.7},
            {"content": "User hates writing CSS", "confidence": 0.6}
        ]
    }

    # Case 1: Context about Python
    context_python = "I need to build a new API, which language should I use?"
    print(f"\nContext: '{context_python}'")
    result_python = format_memory_for_injection(memory_data, max_tokens=1000, current_context=context_python)
    print("Resulting Facts (should prioritize Python):")
    for line in result_python.split("\n"):
        if line.startswith("-"):
            print(line)

    # Case 2: Context about Frontend
    context_web = "The UI is looking a bit slow, how can I improve the performance of my components?"
    print(f"\nContext: '{context_web}'")
    result_web = format_memory_for_injection(memory_data, max_tokens=1000, current_context=context_web)
    print("Resulting Facts (should prioritize React/Next.js and maybe CSS):")
    for line in result_web.split("\n"):
        if line.startswith("-"):
            print(line)

    # Case 3: Context about infra
    context_infra = "How do I deploy this to production?"
    print(f"\nContext: '{context_infra}'")
    result_infra = format_memory_for_injection(memory_data, max_tokens=1000, current_context=context_infra)
    print("Resulting Facts (should prioritize Docker):")
    for line in result_infra.split("\n"):
        if line.startswith("-"):
            print(line)


def test_token_counting():
    print("\nTesting Accurate Token Counting...")
    
    long_fact = "This is a very long fact that contains a lot of technical jargon like LangGraph, MCP, TF-IDF, and Cosine Similarity to test if tiktoken is counting tokens more accurately than the old character-based estimation method which was just length divided by four."
    
    memory_data = {
        "facts": [{"content": long_fact, "confidence": 1.0}]
    }
    
    # Test with a very small token limit
    result = format_memory_for_injection(memory_data, max_tokens=20)
    print(f"Injection with 20 token limit (should be truncated or fit tightly):")
    print(result)

if __name__ == "__main__":
    try:
        test_fact_ranking()
        test_token_counting()
        print("\n✅ All memory system tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        import traceback
        traceback.print_exc()
