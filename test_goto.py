from langgraph.graph import StateGraph
from langgraph.types import Command
import asyncio

def node1(state):
    print("Node 1")
    return {"a": 1}

def node2(state):
    print("Node 2")
    return {"b": 2}

graph = StateGraph(dict)
graph.add_node("n1", node1)
graph.add_node("n2", node2)
graph.set_entry_point("n1")
graph.add_edge("n1", "n2")
compiled = graph.compile()

async def main():
    print("Running with Command(goto='n2')")
    try:
        await compiled.ainvoke(Command(resume=None, goto="n2", update={"a": 100}))
    except Exception as e:
        print("Exception:", type(e), e)

asyncio.run(main())
