import sys
import os
import re
import json

# Import the logic from the actual file
sys.path.append('/home/jrm_fusional/Projects/Christopher-AI')
from christopher import parse_tool_call

def test_parser():
    print("--- Running Parser Tests ---")
    
    # Test 1: Valid Tool Call
    text1 = 'TOOL_CALL: {"tool": "slack_send", "params": {"channel": "#general", "text": "hi"}}'
    tool, params = parse_tool_call(text1)
    assert tool == "slack_send"
    assert params["channel"] == "#general"
    print("✅ Test 1: Valid Tool Call - PASSED")

    # Test 2: Normal Conversation (No Tool)
    text2 = "Hello, how are you?"
    tool, params = parse_tool_call(text2)
    assert tool is None
    assert params == {}
    print("✅ Test 2: Normal Conversation - PASSED")

    # Test 3: False Positive (JSON without prefix)
    text3 = "The result is: {\"status\": \"success\"}"
    tool, params = parse_tool_call(text3)
    assert tool is None
    assert params == {}
    print("✅ Test 3: False Positive (JSON without prefix) - PASSED")

    # Test 4: Multiline Tool Call
    text4 = "I need to do something.\nTOOL_CALL: {\"tool\": \"parse_rss\", \"params\": {\"url\": \"test.com\"}}"
    tool, params = parse_tool_call(text4)
    assert tool == "parse_rss"
    assert params["url"] == "test.com"
    print("✅ Test 4: Multiline Tool Call - PASSED")

if __name__ == "__main__":
    try:
        test_parser()
        print("\n🎉 ALL TESTS PASSED!")
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
