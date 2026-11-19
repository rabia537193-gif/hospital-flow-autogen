import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console

from agents.hospital_agents import build_model_client, create_hospital_team


async def main() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    if not os.getenv("GROQ_API_KEY", "").strip():
        raise RuntimeError(f"GROQ_API_KEY is missing or empty. Check {env_path}")

    model_client = build_model_client()
    agents = create_hospital_team(model_client)

    termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(max_messages=10)
    team = RoundRobinGroupChat(participants=agents, termination_condition=termination)

    task = (
        "Load the hospital snapshot from 'data/hospital_snapshot.json', analyze bed capacity, "
        "staffing gaps, and patient flow bottlenecks, account for missing data, simulate a "
        "4-hour surge of 12 extra admissions with 6 expedited discharges, and produce a "
        "prioritized operational action plan."
    )

    await Console(team.run_stream(task=task))
    await model_client.close()


if __name__ == "__main__":
    asyncio.run(main())