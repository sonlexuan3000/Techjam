import { describe, expect, it } from "vitest";
import {
  PlannerOutputValidationError,
  validatePlannerOutput,
} from "./coordination-graph.js";

const options = {
  availableCapabilities: ["research", "synthesis"],
  maxTasks: 6,
};

function validPlan(): Record<string, unknown> {
  return {
    version: 1,
    summary: "Research two areas and synthesize the result.",
    tasks: [
      {
        key: "research-a",
        title: "Research A",
        instruction: "Analyze approach A.",
        dependsOn: [],
        requiredCapability: "research",
        expectedOutput: "Concise analysis",
      },
      {
        key: "research-b",
        title: "Research B",
        instruction: "Analyze approach B.",
        dependsOn: [],
        requiredCapability: "research",
        expectedOutput: "Concise analysis",
      },
      {
        key: "synthesis",
        title: "Synthesize",
        instruction: "Compare both research results.",
        dependsOn: ["research-a", "research-b"],
        requiredCapability: "synthesis",
        expectedOutput: "Final recommendation",
      },
    ],
    finalTaskKey: "synthesis",
  };
}

function tasksOf(plan: Record<string, unknown>): Array<Record<string, unknown>> {
  return plan.tasks as Array<Record<string, unknown>>;
}

function expectRejected(plan: unknown, message: string | RegExp): void {
  expect(() => validatePlannerOutput(JSON.stringify(plan), options)).toThrow(message);
}

describe("Planner graph validation", () => {
  it("parses a valid DAG", () => {
    expect(validatePlannerOutput(JSON.stringify(validPlan()), options)).toEqual(validPlan());
  });

  it("strips exactly one outer Markdown JSON fence", () => {
    const fenced = "```json\n" + JSON.stringify(validPlan()) + "\n```";
    expect(validatePlannerOutput(fenced, options)).toEqual(validPlan());
  });

  it("rejects non-JSON output without including it in the error", () => {
    const sensitiveOutput = "not JSON ARK_API_KEY=secret-value";
    expect(() => validatePlannerOutput(sensitiveOutput, options)).toThrow(
      "Planner output is not valid JSON",
    );
    try {
      validatePlannerOutput(sensitiveOutput, options);
    } catch (error) {
      expect((error as Error).message).not.toContain("secret-value");
    }
  });

  it("rejects duplicate task keys", () => {
    const plan = validPlan();
    tasksOf(plan)[1]!.key = "research-a";
    expectRejected(plan, "duplicate task keys");
  });

  it("rejects a missing dependency", () => {
    const plan = validPlan();
    tasksOf(plan)[2]!.dependsOn = ["missing-task"];
    expectRejected(plan, "references a missing dependency");
  });

  it("rejects a self-dependency", () => {
    const plan = validPlan();
    tasksOf(plan)[0]!.dependsOn = ["research-a"];
    expectRejected(plan, "cannot depend on itself");
  });

  it.each([
    [
      "two-node cycle",
      [
        { key: "research-a", dependsOn: ["research-b"] },
        { key: "research-b", dependsOn: ["research-a"] },
      ],
    ],
    [
      "multi-node cycle",
      [
        { key: "research-a", dependsOn: ["synthesis"] },
        { key: "research-b", dependsOn: ["research-a"] },
        { key: "synthesis", dependsOn: ["research-b"] },
      ],
    ],
  ])("rejects a %s", (_name, dependencyOverrides) => {
    const plan = validPlan();
    for (const override of dependencyOverrides) {
      const task = tasksOf(plan).find((item) => item.key === override.key);
      if (task) task.dependsOn = override.dependsOn;
    }
    expectRejected(plan, "contains a cycle");
  });

  it("uses the request maxTasks instead of a hard-coded limit", () => {
    expect(() =>
      validatePlannerOutput(JSON.stringify(validPlan()), { ...options, maxTasks: 2 }),
    ).toThrow("task limit of 2");
  });

  it("rejects an unavailable capability without echoing it", () => {
    const plan = validPlan();
    tasksOf(plan)[0]!.requiredCapability = "secret-capability-value";
    try {
      validatePlannerOutput(JSON.stringify(plan), options);
      throw new Error("Expected validation to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(PlannerOutputValidationError);
      expect((error as Error).message).toContain("requires an unavailable capability");
      expect((error as Error).message).not.toContain("secret-capability-value");
    }
  });

  it("rejects a missing final task", () => {
    const plan = validPlan();
    plan.finalTaskKey = "missing-final";
    expectRejected(plan, "finalTaskKey does not reference a task");
  });

  it("rejects an orphan task that does not lead to the final task", () => {
    const plan = validPlan();
    tasksOf(plan)[2]!.dependsOn = ["research-a"];
    expectRejected(plan, "must be on a path leading to finalTaskKey");
  });

  it.each([
    ["invalid key", (plan: Record<string, unknown>) => (tasksOf(plan)[0]!.key = "Bad Key")],
    ["empty title", (plan: Record<string, unknown>) => (tasksOf(plan)[0]!.title = "")],
    [
      "long title",
      (plan: Record<string, unknown>) => (tasksOf(plan)[0]!.title = "x".repeat(121)),
    ],
    [
      "long instruction",
      (plan: Record<string, unknown>) =>
        (tasksOf(plan)[0]!.instruction = "x".repeat(4_001)),
    ],
    [
      "long expected output",
      (plan: Record<string, unknown>) =>
        (tasksOf(plan)[0]!.expectedOutput = "x".repeat(501)),
    ],
    ["wrong version", (plan: Record<string, unknown>) => (plan.version = 2)],
    [
      "forbidden status field",
      (plan: Record<string, unknown>) => (tasksOf(plan)[0]!.status = "ready"),
    ],
  ])("rejects schema violation: %s", (_name, mutate) => {
    const plan = validPlan();
    mutate(plan);
    expectRejected(plan, "failed schema validation");
  });
});
