# Multi-Agent-System LLM-Driven BDI System Generator #
This repository contains a multi-agent system designed to architect, program, and validate other Belief-Desire-Intention (BDI) multi-agent systems within the Jason framework.

By leveraging a pipeline of specialized LLM agents, this tool takes natural language specifications and outputs fully functional, syntactically correct .mas2j and .asl files.

### System Architecture
The project orchestrates several sub-agents in a sequential pipeline.

1.Structural Phase: A single agent designs the MAS configuration file (.mas2j).
2.Research Phase: Two agents concurrently gather BDI theory via local RAG and fetch code examples from Jason's GitHub.
3.Coding & Validation Phase: A coder agent writes the AgentSpeak (.asl) files, while a reviewer tests them locally via the Jason executable. They loop up to 5 times to automatically fix any syntax or runtime errors.
4.Deployment Phase: A final agent saves the fully validated project files to the output directory.

### Prerequisites
To run this environment, you need the following configuration:

-Python 3.8+

-Jason Framework: The jason command must be in your system's PATH, or the JASON_BIN environment variable must point to the executable.

-Dependencies: python-dotenv and the required google.adk libraries.

-API Configuration: The system connects to the UPV PoliGPT API (api.poligpt.upv.es) using the Qwen3.6-35B-A3B-FP8 model. Valid APIkeys   must be provided in a .env file.

## Execution Flow

1. It generates the infrastructure and agent logic based on the prompt.
2.The Reviewer agent tests the system locally using the Jason CLI.
3.If syntax or runtime errors occur, the coding agent attempts to fix them (up to 5 times).
4.Upon successful compilation, the final files are permanently stored in their own project folder inside output/.
