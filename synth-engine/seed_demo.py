"""Seed demo: Customer Support Triage workflow.

This script demonstrates the full synthesis pipeline with the canonical
example from the plan: a customer support triage workflow that:

1. Receives customer messages via webhook
2. Classifies intent and urgency
3. Routes to appropriate handler:
   - Billing issues → Billing drafter
   - Outage reports → Status API check → Outage drafter  
   - Other → Clarification asker
4. Logs to database and responds with JSON

Run this script to test the end-to-end synthesis process.
"""

import asyncio
import json
from pathlib import Path

# The canonical customer support triage prompt
SEED_PROMPT = """
Customer support triage: Webhook receives {customerMessage}. 
Classify intent and urgency. 
If billing issue, draft billing response. 
If outage report, check status API then draft response. 
Otherwise, ask clarifying question. 
Always log to DB and return {category, responseText}.
"""

# Expected workflow structure for validation
EXPECTED_STRUCTURE = {
    "trigger_type": "webhook",
    "has_classifier": True,
    "has_branching": True,
    "branches": ["billing", "outage", "other"],
    "has_merge": True,
    "has_response": True,
    "min_agents": 3,  # classifier + at least 2 drafters
}

# Test cases for the generated workflow
TEST_CASES = [
    {
        "name": "Billing Query",
        "input": {
            "customerMessage": "I was charged twice for my subscription last month. Can you help me get a refund?"
        },
        "expected": {
            "category": "billing",
            "has_response": True,
        },
    },
    {
        "name": "Outage Report",
        "input": {
            "customerMessage": "The service is down! I can't access my dashboard since this morning."
        },
        "expected": {
            "category": "outage",
            "has_response": True,
        },
    },
    {
        "name": "Unclear Message",
        "input": {
            "customerMessage": "Help please"
        },
        "expected": {
            "category": "other",
            "has_response": True,
        },
    },
    {
        "name": "Empty Message",
        "input": {
            "customerMessage": ""
        },
        "expected": {
            "category": "other",
            "has_response": True,
        },
    },
]


async def run_seed_demo():
    """Run the seed demo synthesis."""
    
    print("=" * 60)
    print("ROMA Workflow Synthesizer - Seed Demo")
    print("Customer Support Triage Workflow")
    print("=" * 60)
    print()
    
    print("📝 Input Prompt:")
    print("-" * 40)
    print(SEED_PROMPT.strip())
    print()
    
    try:
        # Import the pipeline
        from app.roma.pipeline import ROMAPipeline
        
        pipeline = ROMAPipeline()
        
        print("🔄 Starting synthesis...")
        print("-" * 40)
        
        # Run synthesis
        result = await pipeline.synthesize(prompt=SEED_PROMPT.strip())
        
        print()
        print("✅ Synthesis Complete!")
        print("-" * 40)
        print(f"Workflow ID: {result.workflow_id}")
        print(f"Iteration ID: {result.iteration_id}")
        print(f"Score: {result.score}/100")
        
        if result.score_breakdown:
            print("\nScore Breakdown:")
            for key, value in result.score_breakdown.items():
                print(f"  - {key}: {value}")
        
        print()
        print("📊 Generated Workflow:")
        print("-" * 40)
        
        workflow_ir = result.workflow_ir
        print(f"Name: {workflow_ir.name}")
        print(f"Description: {workflow_ir.description[:100]}...")
        print()
        
        print("Nodes:")
        print(f"  - Trigger: {workflow_ir.trigger.name} ({workflow_ir.trigger.n8n_node_type})")
        for step in workflow_ir.steps:
            agent_info = f" [Agent: {step.agent.name}]" if step.agent else ""
            print(f"  - {step.name}: {step.n8n_node_type}{agent_info}")
        
        print()
        print(f"Edges: {len(workflow_ir.edges)}")
        for edge in workflow_ir.edges:
            label = f" ({edge.label})" if edge.label else ""
            condition = f" [if: {edge.condition}]" if edge.condition else ""
            print(f"  - {edge.source_id} → {edge.target_id}{label}{condition}")
        
        print()
        print("📋 n8n JSON Generated:")
        print("-" * 40)
        print(f"Nodes in n8n workflow: {len(result.n8n_json.get('nodes', []))}")
        print(f"Connections: {len(result.n8n_json.get('connections', {}))}")
        
        # Save the generated workflow
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        
        # Save WorkflowIR
        ir_path = output_dir / "customer_support_ir.json"
        with open(ir_path, "w") as f:
            json.dump(workflow_ir.model_dump(), f, indent=2, default=str)
        print(f"\n💾 WorkflowIR saved to: {ir_path}")
        
        # Save n8n JSON
        n8n_path = output_dir / "customer_support_n8n.json"
        with open(n8n_path, "w") as f:
            json.dump(result.n8n_json, f, indent=2)
        print(f"💾 n8n JSON saved to: {n8n_path}")
        
        print()
        print("🧪 Test Plan:")
        print("-" * 40)
        for i, test in enumerate(result.test_plan, 1):
            print(f"  {i}. {test.get('name', 'Test')}: {test.get('description', '')[:50]}...")
        
        print()
        print("📖 Rationale:")
        print("-" * 40)
        print(result.rationale)
        
        print()
        print("=" * 60)
        print("Seed demo completed successfully!")
        print("=" * 60)
        
        return result
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running from the synth-engine directory")
        print("and have installed dependencies: pip install -r requirements.txt")
        return None
    except Exception as e:
        print(f"❌ Error during synthesis: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_expected_workflow():
    """Print the expected workflow structure for reference."""
    
    print()
    print("Expected Workflow Structure:")
    print("-" * 40)
    print("""
    [Webhook] ─────────────────────────────────────────────────────────┐
        │                                                              │
        ▼                                                              │
    [Classifier Agent]                                                 │
        │                                                              │
        ├─── category = "billing" ───► [Billing Drafter] ─────┐       │
        │                                                       │       │
        ├─── category = "outage" ────► [Status API] ──────┐   │       │
        │                                    │              │   │       │
        │                                    ▼              │   │       │
        │                              [Outage Drafter] ───┤   │       │
        │                                                   │   │       │
        └─── category = "other" ────► [Clarification] ─────┤   │       │
                                                            │   │       │
                                                            ▼   ▼       │
                                                         [Merge] ◄─────┘
                                                            │
                                                            ▼
                                                      [Log to DB]
                                                            │
                                                            ▼
                                                    [Respond to Webhook]
                                                            │
                                                            ▼
                                                    {category, responseText}
    """)


if __name__ == "__main__":
    print_expected_workflow()
    asyncio.run(run_seed_demo())
