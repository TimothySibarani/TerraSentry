import { describe, expect, it } from "vitest";
import { simplifyAgentBrief } from "./simplify-agent-brief";

describe("simplifyAgentBrief", () => {
	it("returns empty string for empty input", () => {
		expect(simplifyAgentBrief("")).toBe("");
		expect(simplifyAgentBrief("   ")).toBe("");
	});

	it("translates a high-risk agent summary into plain public language", () => {
		const raw = `Both deep dives are complete. All signals are confirmed.

## Evidence Summary
#### 🔴 \`loss_post_cutoff\` — Tree-Cover Loss 2021-2025
- **77.16 ha** of Hansen GFC loss detected within PLY-001 across 2021-2025.
- Loss is distributed across all five years, with a peak of **28.16 ha in 2023**.

#### 🔴 \`concession_overlap\` — Holder Mismatch
- PLY-001 overlaps **440.48 ha** of concessions held by **PT. KARYA TAMA BAKTI MULIA**.
- SUP-001's own HGU (No. 343/HGU/BPN/2020) is **suspended** since 2021.

#### 🔴 \`moratorium_overlap\` — Indonesian Peat Moratorium
- **375.78 ha** of PLY-001 falls within moratorium Feature ID 22471 classified as **Peatland**.`;

		const simplified = simplifyAgentBrief(raw);

		expect(simplified).toContain("Public Summary: What You Need to Know");
		expect(simplified).toContain("77.16 hectares of forest");
		expect(simplified).toContain("28.16 ha in 2023");
		expect(simplified).toContain("PT. KARYA TAMA BAKTI MULIA");
		expect(simplified).toContain("suspended");
		expect(simplified).toContain("375.78 hectares");
		expect(simplified).toContain("High Risk / Non-Compliant");
		expect(simplified).toContain("European Union Deforestation Regulation");
	});

	it("translates a clean/compliant summary into plain public language", () => {
		const raw = `Screening complete. 0.0 ha loss. Active permit verified. No conflicts.`;
		const simplified = simplifyAgentBrief(raw);

		expect(simplified).toContain("No Recent Deforestation Found");
		expect(simplified).toContain("Permits in Good Standing");
		expect(simplified).toContain("Clear / Low Risk");
	});
});
