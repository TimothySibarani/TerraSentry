/**
 * Simplifies technical agent summaries into plain-language, public-friendly explanations.
 * Explains EUDR concepts (cutoff dates, concessions, protected peatlands) in everyday terms.
 */

interface ParsedFindings {
	lossHectares?: string;
	lossPeak?: string;
	hasLoss: boolean;
	hasConcessionConflict: boolean;
	concessionHolders: string[];
	declaredSupplier?: string;
	permitSuspended: boolean;
	permitNumber?: string;
	moratoriumHectares?: string;
	hasMoratorium: boolean;
	peatlandHectares?: string;
	hasPeatland: boolean;
	fireDetections?: number;
	hasFires: boolean;
	isHighRisk: boolean;
	isAmbiguous: boolean;
	gaps: string[];
}

function parseTechnicalDetails(summary: string): ParsedFindings {
	const findings: ParsedFindings = {
		hasLoss: false,
		hasConcessionConflict: false,
		concessionHolders: [],
		permitSuspended: false,
		hasMoratorium: false,
		hasPeatland: false,
		hasFires: false,
		isHighRisk: false,
		isAmbiguous: false,
		gaps: [],
	};

	if (
		/high_risk/i.test(summary) ||
		/score\s*100/i.test(summary) ||
		/non-compliant/i.test(summary)
	) {
		findings.isHighRisk = true;
	}

	if (
		/ambiguous/i.test(summary) ||
		/score\s*50/i.test(summary) ||
		/awaiting_review/i.test(summary)
	) {
		findings.isAmbiguous = true;
	}

	// Tree cover loss
	const lossMatch = summary.match(
		/(\d+(?:\.\d+)?)\s*ha.*?(?:loss|tree-cover|post_cutoff|GFC)/i,
	);
	if (lossMatch) {
		const ha = parseFloat(lossMatch[1]);
		if (ha > 0) {
			findings.hasLoss = true;
			findings.lossHectares = lossMatch[1];
		}
	} else if (
		/loss_post_cutoff/i.test(summary) ||
		/deforestation detected/i.test(summary)
	) {
		findings.hasLoss = true;
	}

	const peakMatch = summary.match(/peak of \*\*?([^*,\n]+)\*\*?/i);
	if (peakMatch) {
		findings.lossPeak = peakMatch[1].trim();
	}

	// Concessions & Permits
	if (
		/suspended/i.test(summary) &&
		(/permit/i.test(summary) || /HGU/i.test(summary))
	) {
		findings.permitSuspended = true;
	}

	const hguMatch = summary.match(/HGU[^\w\d]*([A-Za-z0-9/.-]+)/i);
	if (hguMatch) {
		findings.permitNumber = hguMatch[1];
	}

	if (
		/holder mismatch/i.test(summary) ||
		/neither holder matches/i.test(summary) ||
		/concession_overlap/i.test(summary) ||
		/concession conflict/i.test(summary)
	) {
		findings.hasConcessionConflict = true;
	}

	const holderMatches = summary.matchAll(/\*\*(PT\.?\s+[A-Z0-9\s.-]+?)\*\*/gi);
	for (const m of holderMatches) {
		const name = m[1].trim();
		if (!name.includes("Sumber") && !findings.concessionHolders.includes(name)) {
			findings.concessionHolders.push(name);
		}
	}

	const declaredSupplierMatch = summary.match(
		/(?:declared supplier|supplier)\s+\*\*?([^*\n]+?)\*\*?(?:\s*\(SUP|\.|\n|$)/i,
	);
	if (declaredSupplierMatch) {
		findings.declaredSupplier = declaredSupplierMatch[1].trim();
	}

	// Moratorium & Peatland
	const moratoriumMatch = summary.match(
		/(\d+(?:\.\d+)?)\s*ha.*?(?:moratorium|pippib)/i,
	);
	if (moratoriumMatch) {
		findings.hasMoratorium = true;
		findings.moratoriumHectares = moratoriumMatch[1];
	} else if (/moratorium_overlap/i.test(summary)) {
		findings.hasMoratorium = true;
	}

	const peatMatch = summary.match(
		/(\d+(?:\.\d+)?)\s*ha.*?(?:peatland|peat)/i,
	);
	if (peatMatch) {
		findings.hasPeatland = true;
		findings.peatlandHectares = peatMatch[1];
	} else if (/peat_overlap/i.test(summary)) {
		findings.hasPeatland = true;
	}

	// Fire / Thermal
	const fireMatch = summary.match(
		/(\d+)\s*(?:thermal anomalies|fire detections?)/i,
	);
	if (fireMatch) {
		const count = parseInt(fireMatch[1], 10);
		findings.fireDetections = count;
		findings.hasFires = count > 0;
	}

	// Gaps
	if (/permit expiry/i.test(summary) && /not returned|unknown/i.test(summary)) {
		findings.gaps.push("Permit expiration date is not on public record.");
	}
	if (/peatland depth/i.test(summary)) {
		findings.gaps.push("Subsurface peatland depth has not been mapped.");
	}

	return findings;
}

/**
 * Transforms an agent brief summary into clear, non-technical plain English for public understanding.
 */
export function simplifyAgentBrief(summary: string): string {
	const trimmed = summary.trim();
	if (!trimmed) {
		return "";
	}

	const details = parseTechnicalDetails(trimmed);
	const sections: string[] = [];

	sections.push("### 📢 Public Summary: What You Need to Know");
	sections.push(
		"This due-diligence review checks whether crops from this land comply with the **European Union Deforestation Regulation (EUDR)**. Under EU law, products cannot enter the EU market if they were grown on land deforested after **December 31, 2020**, or if the farming operations lack valid legal land permits.",
	);
	sections.push("---");
	sections.push("### 🔍 Key Findings Explained");

	const bullets: string[] = [];

	// 1. Forest & Tree loss
	if (details.hasLoss) {
		const ha = details.lossHectares
			? `**${details.lossHectares} hectares of forest**`
			: "recent forest clearing";
		const peak = details.lossPeak
			? ` (with highest clearing in ${details.lossPeak})`
			: "";
		bullets.push(
			`* 🌲 **Deforestation Detected (EUDR Violation)**\n  Satellite monitoring confirmed ${ha} was cut down between 2021 and 2025${peak}. Because this occurred after the EU's cutoff date (December 31, 2020), this plot violates the core deforestation-free rule.`,
		);
	} else {
		bullets.push(
			"* 🌲 **No Recent Deforestation Found**\n  Satellite analysis verified no significant tree loss on this plot after the EU cutoff date (December 31, 2020).",
		);
	}

	// 2. Concession & Legal Permits
	if (details.hasConcessionConflict || details.permitSuspended) {
		const parts: string[] = [];
		if (details.hasConcessionConflict) {
			const holders =
				details.concessionHolders.length > 0
					? `belong to other registered holders (${details.concessionHolders.slice(0, 2).join(", ")})`
					: "belong to a different company";
			parts.push(
				`Official land records indicate the concessions on this land ${holders}, rather than the declared supplier.`,
			);
		}
		if (details.permitSuspended) {
			const permit = details.permitNumber
				? `(Permit No. ${details.permitNumber})`
				: "";
			parts.push(
				`The supplier's primary operating permit ${permit} is currently **suspended** by authorities.`,
			);
		}
		bullets.push(
			`* 📋 **Permit & Land Rights Red Flags**\n  ${parts.join(" ")} Operating on unverified land or with a suspended permit prevents legal compliance.`,
		);
	} else {
		bullets.push(
			"* 📋 **Permits in Good Standing**\n  The declared supplier holds active permits and matches the registered land concession.",
		);
	}

	// 3. Protected peatland & Moratorium
	if (details.hasMoratorium || details.hasPeatland) {
		const ha = details.moratoriumHectares
			? `**${details.moratoriumHectares} hectares**`
			: details.peatlandHectares
				? `**${details.peatlandHectares} hectares**`
				: "A substantial portion";
		bullets.push(
			`* 🛑 **Conflict with Protected Peatland**\n  ${ha} of this plot sits on protected peatland subject to a government moratorium that strictly bans commercial clearing and new concessions.`,
		);
	}

	// 4. Fire activity
	if (details.hasFires) {
		bullets.push(
			`* 🔥 **Active Fire Hotspots**\n  Satellite sensors spotted **${details.fireDetections} active fire hotspot(s)** within this plot in the last 30 days.`,
		);
	} else {
		bullets.push(
			"* 🔥 **No Recent Fires Detected**\n  Thermal satellite scans detected no active fire hotspots on this plot over the past 30 days.",
		);
	}

	sections.push(bullets.join("\n\n"));

	// 5. Takeaway
	sections.push("---");
	sections.push("### ⚖️ The Bottom Line");

	if (
		details.hasLoss ||
		details.permitSuspended ||
		details.hasConcessionConflict ||
		details.isHighRisk
	) {
		sections.push(
			"**High Risk / Non-Compliant**: This land plot presents severe legal and environmental concerns under EUDR regulations—specifically post-2020 forest clearance, unconfirmed concessions, or suspended operating permits. Shipments originating from this plot cannot be certified for EU import.",
		);
	} else if (details.isAmbiguous) {
		sections.push(
			"**Ambiguous / Needs Human Review**: Evidence shows borderline indicators or incomplete records that require an expert reviewer to verify before approval.",
		);
	} else {
		sections.push(
			"**Clear / Low Risk**: No evidence of recent deforestation or legal conflicts was found. This plot meets the primary criteria required for EUDR compliance.",
		);
	}

	return sections.join("\n\n");
}
