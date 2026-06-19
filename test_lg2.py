from langgraph.graph import StateGraph
from langgraph.types import interrupt
import asyncio

def node1(state):
    print("Node 1")
    return {"a": 1}

def node2(state):
    print("Node 2")
    interrupt("Interrupting")
    print("Node 2 continued")
    return {"b": 2}

def node3(state):
    print("Node 3")
    return {"c": 3}

graph = StateGraph(dict)
graph.add_node("n1", node1)
graph.add_node("n2", node2)
graph.add_node("n3", node3)
graph.set_entry_point("n1")
graph.add_edge("n1", "n2")
graph.add_edge("n2", "n3")
compiled = graph.compile()

async def main():
    try:
        await compiled.ainvoke({})
    except Exception as e:
        print("Exception:", type(e), e)

asyncio.run(main())