---
title: Multi-Agent Architectures, Agentic Teams, and Handoff Patterns in LangGraph
kind: topic_source
category: computer science
sub_category: ai-engineering
scope: topic
source: "LangGraph Multi-Agent Systems Documentation, Anthropic Building Effective Agents Guide, Hierarchical Multi-Agent Orchestration"
source_date: 2024
topic_tags:
  - langchain
  - langgraph
  - ai-engineering
  - multi-agent-systems
  - agent-teams
  - agent-handoffs
  - subgraphs
---
## Multi-Agent Collaboration Topologies and Decomposition Principles

As enterprise generative AI tasks grow in scope and complexity—such as conducting deep market research, authoring multi-module software codebases, or handling end-to-end customer onboarding—attempting to execute the entire workflow using a single monolithic agent with fifty attached tools inevitably fails.

A single agent burdened with excessive tools suffers from severe cognitive degradation:
- Prompt Context Saturation: Fifty tool JSON schemas consume thousands of prompt tokens, reducing available context for user data and reasoning.
- Tool Selection Confusion: The model struggles to select the correct tool among overlapping, subtly different function signatures, increasing hallucination rates.
- Conflated System Instructions: Competing instructions ("Be concise and friendly" vs. "Be rigorous and execute exhaustive data audits") conflict within a single prompt.

Senior AI engineers decompose complex domains into specialized multi-agent teams. Each agent is modeled as an independent cognitive persona possessing a focused system prompt, a small set of tightly scoped tools (typically three to five), and a dedicated role (e.g., a Researcher, an Analyst, a Code Author, and a Reviewer). LangGraph orchestrates these specialized agents into cohesive teams through three foundational collaboration topologies: the Central Supervisor, Peer-to-Peer Handoffs, and Hierarchical Subgraphs.

## The Central Supervisor Pattern and Dynamic Worker Delegation

The Central Supervisor topology is an agentic team structure modeled after a human engineering manager coordinating a team of specialists:
- Architecture: A central "supervisor" language model acts as the root orchestrator. It does not execute technical tools directly; instead, its prompt is primed with high-level coordination instructions and a tool or router interface listing the available worker agents (e.g., `["web_researcher", "sql_analyst", "chart_generator"]`).
- Execution Flow:
  1. The user submits a complex goal: "Analyze our Q3 sales trends and visualize customer churn."
  2. The supervisor analyzes the request, decomposes it into discrete steps, and delegates the first task by returning `{"next": "sql_analyst"}`.
  3. The graph routes execution to the `sql_analyst` node, which executes database queries and returns tabular data.
  4. Execution loops back to the supervisor. The supervisor inspects the SQL output and routes to `chart_generator`.
  5. Once the chart is generated, the supervisor determines that all goals are met and routes to `FINISH`, synthesizing the final comprehensive answer to the user.
- State Management: Workers typically share a unified conversation state log or receive isolated task inputs, allowing the supervisor to maintain centralized governance over execution progress and enforce maximum iteration limits.

## Peer-to-Peer Agent Handoffs via the Command Primitive

In collaborative environments where work flows sequentially or where specialized agents must handle different phases of an interactive user dialogue (such as customer support routing), the Central Supervisor pattern introduces unnecessary orchestration overhead.

Instead, teams implement Peer-to-Peer Agent Handoffs:
- In a handoff architecture, agents communicate directly with one another without routing back through a central supervisor.
- Modern LangGraph implements handoffs cleanly using the `Command` primitive:
```python
from langgraph.types import Command
from typing import Literal

def triage_agent_node(state: SupportState) -> Command[Literal["billing_agent", "tech_agent", "__end__"]]:
    messages = state["messages"]
    response = triage_model.invoke(messages)
    
    if "billing" in response.content.lower():
        return Command(
            update={"messages": [AIMessage(content="Transferring you to our billing specialist.")]},
            goto="billing_agent"
        )
    elif "technical" in response.content.lower():
        return Command(
            update={"messages": [AIMessage(content="Transferring you to technical support.")]},
            goto="tech_agent"
        )
    return Command(update={"messages": [response]}, goto=END)
```
When `triage_agent_node` returns `Command(goto="billing_agent")`, LangGraph immediately routes execution to the `billing_agent` node in the next super-step. The billing agent receives the updated state, inherits conversation context, and continues the dialogue seamlessly.

## Hierarchical Subgraphs as Nodes and Upward Parent Navigation

For large-scale enterprise cognitive architectures, flat graphs containing dozens of nodes become unwieldy to maintain, test, and debug. LangGraph provides native support for Hierarchical Subgraphs:
- A subgraph is an independent, fully functional `StateGraph` with its own specialized state schema, internal nodes, cyclic loops, and checkpointers.
- A parent graph can embed the entire compiled subgraph as a single callable node:
  `parent_graph.add_node("research_team", compiled_research_subgraph)`
- Encapsulated Isolation: The internal mechanics, scratchpad reasoning, and intermediate tool messages of the research team remain completely encapsulated inside the subgraph. Only the final synthesized report is mapped back into the parent graph's state schema.
- Parent Navigation via `Command.PARENT`: Modern LangGraph enables subgraphs to communicate upward to the parent graph. A node inside a nested subgraph can return:
  ```python
  return Command(
      update={"final_research_report": report_content},
      goto="lead_editor",
      graph=Command.PARENT
  )
  ```
  This signals the orchestrator to exit the subgraph immediately and transition directly to the `lead_editor` node inside the enclosing parent graph, providing powerful multi-level team coordination.

## Pre-Built ReAct Loops via create_react_agent and ToolNode Architecture

While building custom `StateGraph` definitions provides maximum control for bespoke workflows, the standard ReAct (Reasoning + Acting) loop is so prevalent that LangGraph provides a high-performance pre-built implementation:
```python
from langgraph.prebuilt import create_react_agent, ToolNode

tools = [search_database, calculate_metric]
tool_node = ToolNode(tools)

agent = create_react_agent(
    model=chat_model,
    tools=tools,
    checkpointer=checkpointer,
    state_modifier="You are an expert financial auditor. Always verify data using tools."
)
```
Under the hood, `create_react_agent` compiles an optimized `StateGraph` consisting of:
1. An Agent Model Node: Invokes the model with `bind_tools(tools)` and the conversation messages.
2. A `ToolNode`: Automatically inspects `AIMessage.tool_calls`, executes the corresponding Python functions concurrently using `asyncio`, formats results into `ToolMessage` instances, and appends them to the state.
3. A Pre-Built Conditional Edge: Checks whether the model returned `tool_calls`. If yes, it routes to `ToolNode`, which loops back to the model node; if no, it routes to `END`.
`create_react_agent` serves as the modern, fully supported replacement for LangChain's legacy `AgentExecutor`, delivering native persistence, token streaming, and multi-agent composability out of the box.
