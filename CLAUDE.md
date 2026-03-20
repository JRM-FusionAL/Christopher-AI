# Claude Session Bootstrap

Use the FusionAL knowledge base as the default source of truth for context before making changes.

## Always Load First
1. C:\\Users\\puddi\\Projects\\fusional-knowledge-base\\00-CURRENT-STATUS\\STATUS.md
2. C:\\Users\\puddi\\Projects\\fusional-knowledge-base\\00-CURRENT-STATUS\\PRIORITIES.md

## Then Load If Needed
- C:\\Users\\puddi\\Projects\\fusional-knowledge-base\\06-CONTEXT\\FAQ.md
- C:\\Users\\puddi\\Projects\\fusional-knowledge-base\\06-CONTEXT\\DECISIONS.md

## Working Rule
- If repo/runtime facts conflict with docs, trust verified code/runtime facts.
- Call out the mismatch and update the knowledge base during the same task.

## Prompt Shortcut
Read STATUS.md and PRIORITIES.md from fusional-knowledge-base first, then answer using that context.
