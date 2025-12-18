from aiogram.fsm.state import State, StatesGroup
from fastapi.encoders import jsonable_encoder

class MyStates(StatesGroup):
    step1 = State()

step_with_state = {
    "name": "step1",
    "state": MyStates.step1
}

print(f"Original state type: {type(step_with_state['state'])}")

# Simulate the fix
safe_step = step_with_state.copy()
safe_step["state"] = str(safe_step["state"])

print(f"Sanitized state type: {type(safe_step['state'])}")
print(f"Sanitized state value: {safe_step['state']}")

try:
    encoded = jsonable_encoder(safe_step)
    print("Serialization SUCCESS!")
    print(encoded)
except Exception as e:
    print(f"Serialization FAILED: {e}")
