"""Utility to print n8n workflows in clean text representation."""

from typing import Optional, Union
import json


def print_workflow(workflow: dict, include_params: bool = False) -> str:
    """
    Convert an n8n workflow JSON to a clean text representation.
    
    Args:
        workflow: n8n workflow JSON object
        include_params: Include node parameters in output (default: False)
    
    Returns:
        Formatted string representation of the workflow
    """
    lines = []
    
    # Header
    name = workflow.get("name", "Unnamed Workflow")
    lines.append("=" * 60)
    lines.append(f"  WORKFLOW: {name}")
    lines.append("=" * 60)
    
    # Metadata
    workflow_id = workflow.get("id", "N/A")
    active = workflow.get("active", False)
    lines.append(f"  ID: {workflow_id}")
    lines.append(f"  Active: {'✓ Yes' if active else '✗ No'}")
    lines.append("")
    
    # Get nodes and connections
    nodes = workflow.get("nodes", [])
    connections = workflow.get("connections", {})
    
    # Build node lookup
    node_lookup = {node.get("name"): node for node in nodes}
    
    # Find trigger node (usually first or webhook type)
    trigger_node = None
    for node in nodes:
        node_type = node.get("type", "")
        if "webhook" in node_type.lower() or "trigger" in node_type.lower() or "manual" in node_type.lower():
            trigger_node = node
            break
    if not trigger_node and nodes:
        trigger_node = nodes[0]
    
    # Print nodes section
    lines.append("  NODES:")
    lines.append("  " + "-" * 56)
    
    for i, node in enumerate(nodes, 1):
        node_name = node.get("name", f"Node {i}")
        node_type = node.get("type", "unknown")
        type_version = node.get("typeVersion", 1)
        
        # Simplify type name
        short_type = node_type.replace("n8n-nodes-base.", "").replace("n8n-nodes-", "")
        
        # Get position
        pos = node.get("position", [0, 0])
        
        # Icon based on type
        icon = _get_node_icon(node_type)
        
        lines.append(f"  {icon} [{i}] {node_name}")
        lines.append(f"       Type: {short_type} (v{type_version})")
        lines.append(f"       Position: ({pos[0]}, {pos[1]})")
        
        # Include parameters if requested
        if include_params:
            params = node.get("parameters", {})
            if params:
                lines.append("       Parameters:")
                for key, value in params.items():
                    value_str = _format_param_value(value)
                    lines.append(f"         • {key}: {value_str}")
        
        lines.append("")
    
    # Print connections/flow
    lines.append("  FLOW:")
    lines.append("  " + "-" * 56)
    
    if connections:
        flow_lines = _build_flow_diagram(nodes, connections)
        for line in flow_lines:
            lines.append(f"  {line}")
    else:
        lines.append("  (No connections defined)")
    
    lines.append("")
    
    # Print webhook info if present
    webhook_path = None
    for node in nodes:
        if "webhook" in node.get("type", "").lower():
            params = node.get("parameters", {})
            webhook_path = params.get("path")
            http_method = params.get("httpMethod", "POST")
            if webhook_path:
                lines.append("  WEBHOOK:")
                lines.append("  " + "-" * 56)
                lines.append(f"  Method: {http_method}")
                lines.append(f"  Path: /{webhook_path}")
                lines.append("")
                break
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


def print_workflow_ir(workflow_ir: dict) -> str:
    """
    Convert a WorkflowIR to a clean text representation.
    
    Args:
        workflow_ir: WorkflowIR object/dict
    
    Returns:
        Formatted string representation
    """
    lines = []
    
    # Header
    name = workflow_ir.get("name", "Unnamed Workflow")
    lines.append("=" * 60)
    lines.append(f"  WORKFLOW IR: {name}")
    lines.append("=" * 60)
    
    # Description
    desc = workflow_ir.get("description", "")
    if desc:
        lines.append(f"  Description: {desc[:80]}...")
    
    # Trigger
    trigger = workflow_ir.get("trigger", {})
    if trigger:
        trigger_type = trigger.get("trigger_type", "unknown")
        params = trigger.get("parameters", {})
        lines.append("")
        lines.append("  TRIGGER:")
        lines.append("  " + "-" * 56)
        lines.append(f"  ⚡ Type: {trigger_type}")
        if params.get("path"):
            lines.append(f"     Path: /{params['path']}")
        if params.get("httpMethod"):
            lines.append(f"     Method: {params['httpMethod']}")
        if params.get("schedule"):
            sched = params["schedule"]
            lines.append(f"     Schedule: Every {sched.get('value')} {sched.get('unit')}")
    
    # Steps
    steps = workflow_ir.get("steps", [])
    if steps:
        lines.append("")
        lines.append("  STEPS:")
        lines.append("  " + "-" * 56)
        
        for i, step in enumerate(steps, 1):
            step_name = step.get("name", f"Step {i}")
            step_type = step.get("type", "action")
            n8n_type = step.get("n8n_node_type", "unknown").replace("n8n-nodes-base.", "")
            
            icon = _get_step_icon(step_type)
            
            lines.append(f"  {icon} [{i}] {step_name}")
            lines.append(f"       Type: {step_type} → {n8n_type}")
            
            # Agent info
            agent = step.get("agent")
            if agent:
                lines.append(f"       Agent: {agent.get('name', 'unnamed')}")
                if agent.get("role"):
                    lines.append(f"       Role: {agent['role'][:60]}...")
            
            # Description
            if step.get("description"):
                lines.append(f"       Desc: {step['description'][:60]}...")
            
            lines.append("")
    
    # Edges
    edges = workflow_ir.get("edges", [])
    if edges:
        lines.append("  EDGES:")
        lines.append("  " + "-" * 56)
        for edge in edges:
            from_step = edge.get("from_step", "?")
            to_step = edge.get("to_step", "?")
            condition = edge.get("condition")
            
            arrow = f"  {from_step} ──→ {to_step}"
            if condition:
                arrow += f" (if: {condition})"
            lines.append(arrow)
        lines.append("")
    
    # Test invariants
    tests = workflow_ir.get("test_invariants", [])
    if tests:
        lines.append("  TESTS:")
        lines.append("  " + "-" * 56)
        for test in tests:
            lines.append(f"  ✓ {test.get('name', 'Test')}: {test.get('description', '')[:50]}")
        lines.append("")
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


def print_workflow_compact(workflow: dict) -> str:
    """
    Print a compact one-line-per-node representation.
    
    Args:
        workflow: n8n workflow JSON
    
    Returns:
        Compact string representation
    """
    lines = []
    
    name = workflow.get("name", "Unnamed")
    nodes = workflow.get("nodes", [])
    connections = workflow.get("connections", {})
    
    lines.append(f"📋 {name}")
    lines.append("")
    
    # Build flow
    node_names = [n.get("name") for n in nodes]
    
    # Simple linear flow representation
    flow_parts = []
    for node in nodes:
        node_name = node.get("name", "?")
        node_type = node.get("type", "").replace("n8n-nodes-base.", "")
        icon = _get_node_icon(node.get("type", ""))
        flow_parts.append(f"{icon} {node_name}")
    
    # Connect with arrows
    lines.append(" → ".join(flow_parts))
    
    return "\n".join(lines)


def _get_node_icon(node_type: str) -> str:
    """Get an icon for a node type."""
    type_lower = node_type.lower()
    
    if "webhook" in type_lower:
        return "🔗"
    elif "http" in type_lower:
        return "🌐"
    elif "agent" in type_lower or "ai" in type_lower:
        return "🤖"
    elif "set" in type_lower:
        return "📝"
    elif "if" in type_lower or "switch" in type_lower:
        return "🔀"
    elif "respond" in type_lower:
        return "📤"
    elif "itemlist" in type_lower or "split" in type_lower:
        return "🔄"
    elif "aggregate" in type_lower or "merge" in type_lower:
        return "📦"
    elif "slack" in type_lower:
        return "💬"
    elif "email" in type_lower or "gmail" in type_lower:
        return "📧"
    elif "database" in type_lower or "postgres" in type_lower or "mysql" in type_lower:
        return "🗄️"
    elif "schedule" in type_lower or "cron" in type_lower:
        return "⏰"
    else:
        return "⚙️"


def _get_step_icon(step_type: str) -> str:
    """Get an icon for a step type."""
    icons = {
        "trigger": "⚡",
        "action": "⚙️",
        "transform": "🔄",
        "agent": "🤖",
        "branch": "🔀",
        "merge": "📦",
    }
    return icons.get(step_type, "•")


def _format_param_value(value, max_len: int = 50) -> str:
    """Format a parameter value for display."""
    if isinstance(value, str):
        if len(value) > max_len:
            return f'"{value[:max_len]}..."'
        return f'"{value}"'
    elif isinstance(value, dict):
        return f"{{...}} ({len(value)} keys)"
    elif isinstance(value, list):
        return f"[...] ({len(value)} items)"
    else:
        return str(value)


def _build_flow_diagram(nodes: list, connections: dict) -> list:
    """Build a simple text flow diagram."""
    lines = []
    
    # Map node names to simple indices
    node_indices = {node.get("name"): i for i, node in enumerate(nodes)}
    
    # Track which nodes connect to which
    graph = {}
    for source_name, conn_data in connections.items():
        if "main" in conn_data:
            for output_idx, targets in enumerate(conn_data["main"]):
                for target in targets:
                    target_name = target.get("node")
                    if target_name:
                        if source_name not in graph:
                            graph[source_name] = []
                        graph[source_name].append(target_name)
    
    # Find starting nodes (no incoming connections)
    all_targets = set()
    for targets in graph.values():
        all_targets.update(targets)
    
    start_nodes = [n.get("name") for n in nodes if n.get("name") not in all_targets]
    
    # Simple linear representation
    visited = set()
    
    def traverse(node_name, depth=0):
        if node_name in visited:
            return
        visited.add(node_name)
        
        indent = "  " * depth
        icon = _get_node_icon(next((n.get("type", "") for n in nodes if n.get("name") == node_name), ""))
        lines.append(f"{indent}{icon} {node_name}")
        
        if node_name in graph:
            targets = graph[node_name]
            for i, target in enumerate(targets):
                connector = "└──→ " if i == len(targets) - 1 else "├──→ "
                lines.append(f"{indent}  {connector}")
                traverse(target, depth + 1)
    
    for start in start_nodes:
        traverse(start)
    
    return lines if lines else ["(No flow connections)"]


# Convenience function for CLI usage
def print_n8n_workflow(workflow_json: Union[str, dict]) -> None:
    """
    Print an n8n workflow to stdout.
    
    Args:
        workflow_json: JSON string or dict of n8n workflow
    """
    if isinstance(workflow_json, str):
        workflow = json.loads(workflow_json)
    else:
        workflow = workflow_json
    
    print(print_workflow(workflow, include_params=False))


def print_n8n_workflow_detailed(workflow_json: Union[str, dict]) -> None:
    """
    Print an n8n workflow with full parameters to stdout.
    
    Args:
        workflow_json: JSON string or dict of n8n workflow
    """
    if isinstance(workflow_json, str):
        workflow = json.loads(workflow_json)
    else:
        workflow = workflow_json
    
    print(print_workflow(workflow, include_params=True))


# Example usage
if __name__ == "__main__":
    # Example workflow
    example = {
        "name": "Apollo Prospect Research",
        "id": "abc123",
        "active": True,
        "nodes": [
            {
                "name": "Trigger",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 1,
                "position": [200, 200],
                "parameters": {"path": "prospect-search", "httpMethod": "POST"}
            },
            {
                "name": "Search Apollo",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4,
                "position": [400, 200],
                "parameters": {"url": "https://api.example.com", "method": "POST"}
            },
            {
                "name": "Loop Prospects",
                "type": "n8n-nodes-base.itemLists",
                "typeVersion": 3,
                "position": [600, 200],
                "parameters": {"operation": "splitOutItems"}
            },
            {
                "name": "Research Agent",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4,
                "position": [800, 200],
                "parameters": {}
            },
            {
                "name": "Respond",
                "type": "n8n-nodes-base.respondToWebhook",
                "typeVersion": 1,
                "position": [1000, 200],
                "parameters": {}
            }
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "Search Apollo"}]]},
            "Search Apollo": {"main": [[{"node": "Loop Prospects"}]]},
            "Loop Prospects": {"main": [[{"node": "Research Agent"}]]},
            "Research Agent": {"main": [[{"node": "Respond"}]]}
        }
    }
    
    print(print_workflow(example))
    print("\n" + "="*60 + "\n")
    print(print_workflow_compact(example))
