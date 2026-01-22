---
description: Code review focusing on simplification and clarity
---

# Code Review

You are tasked with performing a thorough code review of recently modified code, focusing on clarity, consistency, and maintainability while preserving all functionality.

**Usage**:
- `/review` - Review all recently modified files
- `/review <file-path>` - Review specific file

## Important Context

This repository is primarily Python-based. The codebase includes:
- Python services in `services/` directory (Python 3.11)
- TypeScript server code in `platform/` directory (Bun + Elysia)
- Refer to [CLAUDE.md](CLAUDE.md) for architecture details

## Process Overview

### 1. Identify Scope

**If no arguments provided**:
- Check git status to find recently modified files
- Ask user which files they want reviewed
- Focus on uncommitted changes by default

**If file path provided**:
- Review the specified file
- Consider related files if needed for context

### 2. Use Code Simplifier Agent

The primary tool for code review is the **code-simplifier** agent. This agent:
- Focuses on recently modified code unless instructed otherwise
- Simplifies and refines code for clarity, consistency, and maintainability
- Preserves all functionality while improving code quality
- Has access to all tools needed for comprehensive review

**Spawn the agent with clear instructions**:
```
Use the Task tool with subagent_type="code-simplifier"

Provide specific guidance:
- Which files to review (or "recently modified")
- Specific concerns if any (e.g., error handling, naming conventions)
- Whether to make changes or just report findings
```

### 3. Review Focus Areas

Guide the code-simplifier agent to evaluate:

**Code Quality:**
- Clarity and readability
- Naming conventions (clear, descriptive names)
- Function/method length (single responsibility)
- Complex logic that could be simplified
- Duplicate or near-duplicate code

**Python-Specific (majority of codebase):**
- PEP 8 compliance (use `black` and `ruff` for automated checks)
- Type hints where beneficial
- Pythonic idioms and patterns
- Error handling (custom `ApolloError` class)
- Docstrings for public functions/classes

**TypeScript-Specific:**
- Type safety and proper types
- Consistent patterns with Elysia framework
- Async/await usage
- Error handling

**Security:**
- No hardcoded secrets or API keys (should use `.env`)
- Input validation at system boundaries
- Protection against common vulnerabilities (XSS, SQL injection, etc.)

**Architecture Alignment:**
- Follows existing patterns in the codebase
- Proper separation of concerns
- Consistent with service architecture

### 4. Review Modes

**Report-Only Mode** (default):
- Agent identifies issues and suggestions
- Creates a summary report
- User decides what to address

**Interactive Mode**:
- Agent proposes specific changes
- User approves each change before applying
- Iterative refinement

**Auto-Fix Mode** (use with caution):
- Agent applies obvious improvements automatically
- Reports all changes made
- Best for formatting and simple clarity fixes

### 5. Generate Review Summary

After the code-simplifier agent completes, synthesize findings:

```markdown
## Code Review Summary

### Files Reviewed
- `path/to/file.py`
- `path/to/another.ts`

### Key Findings

#### Clarity Improvements
- [File:line] - Suggestion with rationale

#### Consistency Issues
- [File:line] - How to align with codebase patterns

#### Potential Issues
- [File:line] - Security, performance, or correctness concerns

#### Positive Patterns
- Highlight good practices worth maintaining

### Automated Checks

Run quality tools:
```bash
# Python
black services/ --check
ruff check services/

# TypeScript (if applicable)
cd platform && bun test
```

### Recommendations

Prioritized list of changes:
1. **Critical**: Must address before merge
2. **Important**: Should address soon
3. **Nice-to-have**: Consider for future cleanup
```

### 6. Follow-Up Actions

Present findings and ask:
- "Would you like me to apply any of these suggestions?"
- "Should I focus on any particular area?"
- "Do you want me to review related files?"

## Command Integration

This command works well in workflows:

1. `/research-codebase` - Understand the code context
2. [Make changes]
3. `/review` - Review the changes
4. `/commit` - Commit reviewed code
5. `/validate-plan` - Ensure changes meet requirements

## Important Guidelines

**Be Constructive:**
- Focus on improvements, not criticism
- Explain the "why" behind suggestions
- Acknowledge good patterns in the code

**Be Practical:**
- Don't suggest over-engineering
- Balance perfection with pragmatism
- Consider the scope of changes

**Be Consistent:**
- Reference existing codebase patterns
- Suggest changes that align with project style
- Use automated tools (black, ruff) as source of truth

**Preserve Functionality:**
- NEVER suggest changes that alter behavior
- Maintain all existing functionality
- Test coverage should remain the same or improve

**Respect Context:**
- Understand the code's purpose before suggesting changes
- Consider performance implications
- Account for existing technical decisions

## Examples

### Example 1: Review Recent Changes
```
User: /review
Assistant: Let me check what files have been modified recently.
[Checks git status]
I see changes in services/job_chat/job_chat.py and platform/src/server.ts.
I'll use the code-simplifier agent to review these files.
[Spawns code-simplifier agent]
[Presents summary of findings]
```

### Example 2: Review Specific File
```
User: /review services/vocab_mapper/vocab_mapper.py
Assistant: I'll review the vocab mapper service for clarity and maintainability.
[Spawns code-simplifier agent with specific file]
[Presents findings focusing on that file]
```

### Example 3: Pre-Commit Review
```
User: Can you review my changes before I commit?
Assistant: I'll perform a comprehensive review of your uncommitted changes.
[Reviews all modified files]
[Runs automated checks]
[Provides summary and asks if user wants to apply suggestions]
```

## Quality Standards

Code should meet these standards:
- **Readable**: Clear intent, good names, logical flow
- **Maintainable**: Easy to modify, well-structured, documented where needed
- **Consistent**: Follows project conventions and patterns
- **Functional**: Does what it's supposed to, handles errors appropriately
- **Secure**: No vulnerabilities, validates inputs, protects secrets

Remember: The goal is to make the code better while preserving what it does. Review is about clarity and consistency, not rewriting.
