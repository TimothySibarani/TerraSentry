import type { EvidenceEntry } from "@terrasentry/api-client";
import { FlameIcon, LeafIcon, ZapIcon } from "lucide-react";
import { useMemo } from "react";

import { MapView, type MapTone } from "#/components/map/map-view";
import { MetricCard } from "#/components/metric-card";
import {
	decodeDetections,
	decodeGeometry,
	findEvidence,
	numberValue,
} from "#/features/runs/evidence";
import { formatNumber } from "#/lib/format";

export function RunMapPanel({
	entries,
	tone,
	label,
}: {
	entries: ReadonlyArray<EvidenceEntry>;
	tone: MapTone;
	label: string;
}) {
	const lens = useMemo(() => {
		const geometryEntry = findEvidence(entries, "parcel.geometry");
		const geometry = geometryEntry ? decodeGeometry(geometryEntry.value) : null;
		const detectionsEntry = findEvidence(entries, "hotspots.detections");
		const detections = detectionsEntry
			? decodeDetections(detectionsEntry.value)
			: [];
		return {
			loss: numberValue(findEvidence(entries, "loss.total_loss_ha")?.value),
			detectionCount: numberValue(
				findEvidence(entries, "hotspots.detection_count")?.value,
			),
			totalFrp: numberValue(findEvidence(entries, "hotspots.total_frp")?.value),
			polygons: geometry
				? [
						{
							id: label,
							geometry,
							label,
							detail: "Parcel geometry from the synthetic concession dataset",
							tone,
						},
					]
				: [],
			points: detections.map((detection, index) => ({
				id: `hotspot-${index}`,
				longitude: detection.longitude,
				latitude: detection.latitude,
				label: `Fire detection · ${detection.acq_date}`,
				detail: `FRP ${detection.frp ?? "—"} MW · ${detection.confidence ?? "n/a"} confidence`,
				frp: detection.frp,
			})),
		};
	}, [entries, label, tone]);
	const { loss, detectionCount, totalFrp, polygons, points } = lens;

	return (
		<div className="flex flex-col gap-4">
			<div className="grid gap-4 sm:grid-cols-3">
				<MetricCard
					label="Tree-cover loss"
					value={
						<span className="flex items-baseline gap-1">
							{formatNumber(loss)}
							<span className="text-body-sm text-muted-foreground">ha</span>
						</span>
					}
					hint={
						<span className="flex items-center gap-1">
							<LeafIcon aria-hidden="true" className="size-3" />
							GFW/Hansen, 5-year window
						</span>
					}
				/>
				<MetricCard
					label="Fire detections"
					value={formatNumber(detectionCount)}
					hint={
						<span className="flex items-center gap-1">
							<FlameIcon aria-hidden="true" className="size-3" />
							NASA FIRMS, 30-day window
						</span>
					}
				/>
				<MetricCard
					label="Total FRP"
					value={
						<span className="flex items-baseline gap-1">
							{formatNumber(totalFrp)}
							<span className="text-body-sm text-muted-foreground">MW</span>
						</span>
					}
					hint={
						<span className="flex items-center gap-1">
							<ZapIcon aria-hidden="true" className="size-3" />
							Sum over detections
						</span>
					}
				/>
			</div>
			<MapView polygons={polygons} points={points} />
		</div>
	);
}
