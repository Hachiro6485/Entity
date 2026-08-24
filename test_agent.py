from core.planner import generate_plan
from core.executor import execute_plan

# 1. The User's Goal
goal = "Search the web for the weather in New York, and then run a python script to print that weather data."

# 2. Generate the Blueprint
print("🧠 PLANNING...")
plan = generate_plan(goal)

import json
print("\n📝 THE BLUEPRINT:")
print(json.dumps(plan, indent=4))

# 3. Execute the Blueprint
if plan:
    execute_plan(plan)
else:
    print("Failed to generate a plan.")