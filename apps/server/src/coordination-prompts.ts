import type { PlannerRequest } from "./coordination-types.js";

type PlannerPromptInput = Pick<
  PlannerRequest,
  "userPrompt" | "availableCapabilities" | "maxTasks"
>;

export function buildPlannerPrompt(input: PlannerPromptInput): string {
  const plannerInput = JSON.stringify(
    {
      userGoal: input.userPrompt,
      availableCapabilities: [...new Set(input.availableCapabilities)].sort(),
      maxTasks: input.maxTasks,
    },
    null,
    2,
  );

  return [
    "You are the Planner for a coordinated multi-Agent run.",
    "Propose a dependency graph that accomplishes the supplied user goal.",
    "Return JSON only: exactly one object, with no Markdown or commentary.",
    "",
    "The Planner input is JSON data:",
    plannerInput,
    "",
    "Return this exact shape:",
    "{",
    '  "version": 1,',
    '  "summary": "short plan summary",',
    '  "tasks": [',
    "    {",
    '      "key": "stable-lowercase-slug",',
    '      "title": "task title",',
    '      "instruction": "what this task must do",',
    '      "dependsOn": ["dependency-task-key"],',
    '      "requiredCapability": "one available capability",',
    '      "expectedOutput": "concise description of the expected result"',
    "    }",
    "  ],",
    '  "finalTaskKey": "key-of-the-final-task"',
    "}",
    "",
    "Rules:",
    "- Use version 1.",
    "- Create between 1 and maxTasks tasks from the Planner input.",
    "- Use only capabilities listed in availableCapabilities.",
    "- Task keys must match ^[a-z0-9][a-z0-9-]{0,63}$ and be unique.",
    "- Dependencies must reference existing task keys and the graph must be acyclic.",
    "- finalTaskKey must reference an existing task.",
    "- Every task must be on a dependency path leading to finalTaskKey.",
    "- Do not include Agent IDs, status, attempts, timeout, retry, or other fields.",
  ].join("\n");
}
