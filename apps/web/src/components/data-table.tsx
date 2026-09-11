import {
	type ColumnDef,
	createSortedRowModel,
	type RowData,
	rowSortingFeature,
	sortFns,
	tableFeatures,
	useTable,
} from "@tanstack/react-table";
import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon } from "lucide-react";

import { Button } from "#/components/ui/button";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "#/components/ui/table";
import { cn } from "#/lib/utils";

export const tableFeatureSet = tableFeatures({
	rowSortingFeature,
	sortedRowModel: createSortedRowModel(),
	sortFns,
});

export type TableFeatureSet = typeof tableFeatureSet;

export interface DataTableProps<TData extends RowData> {
	columns: ReadonlyArray<ColumnDef<TableFeatureSet, TData>>;
	data: ReadonlyArray<TData>;
	caption?: string;
	emptyMessage?: string;
	initialSorting?: ReadonlyArray<{ id: string; desc: boolean }>;
	getRowId?: (row: TData) => string;
	onRowClick?: (row: TData) => void;
	className?: string;
}

export function DataTable<TData extends RowData>({
	columns,
	data,
	caption,
	emptyMessage = "Nothing to show yet.",
	initialSorting,
	getRowId,
	onRowClick,
	className,
}: DataTableProps<TData>) {
	const table = useTable({
		features: tableFeatureSet,
		columns,
		data,
		...(getRowId ? { getRowId: (row: TData) => getRowId(row) } : {}),
		...(initialSorting
			? { initialState: { sorting: [...initialSorting] } }
			: {}),
	});

	return (
		<div
			className={cn(
				"overflow-hidden rounded-lg border border-border",
				className,
			)}
		>
			<Table>
				{caption && <caption className="sr-only">{caption}</caption>}
				<TableHeader>
					{table.getHeaderGroups().map((headerGroup) => (
						<TableRow key={headerGroup.id}>
							{headerGroup.headers.map((header) => {
								const sorted = header.column.getIsSorted();
								const canSort = header.column.getCanSort();
								return (
									<TableHead
										key={header.id}
										aria-sort={
											sorted === "asc"
												? "ascending"
												: sorted === "desc"
													? "descending"
													: canSort
														? "none"
														: undefined
										}
									>
										{header.isPlaceholder ? null : canSort ? (
											<Button
												variant="ghost"
												size="xs"
												className="-ml-2 text-caption-mono-sm text-muted-foreground uppercase"
												onClick={header.column.getToggleSortingHandler()}
											>
												<table.FlexRender header={header} />
												{sorted === "asc" ? (
													<ArrowUpIcon
														data-icon="inline-end"
														aria-hidden="true"
													/>
												) : sorted === "desc" ? (
													<ArrowDownIcon
														data-icon="inline-end"
														aria-hidden="true"
													/>
												) : (
													<ChevronsUpDownIcon
														data-icon="inline-end"
														aria-hidden="true"
													/>
												)}
											</Button>
										) : (
											<table.FlexRender header={header} />
										)}
									</TableHead>
								);
							})}
						</TableRow>
					))}
				</TableHeader>
				<TableBody>
					{table.getRowModel().rows.length === 0 ? (
						<TableRow>
							<TableCell
								colSpan={columns.length}
								className="h-24 text-center text-body-sm text-muted-foreground"
							>
								{emptyMessage}
							</TableCell>
						</TableRow>
					) : (
						table.getRowModel().rows.map((row) => (
							<TableRow
								key={row.id}
								tabIndex={onRowClick ? 0 : undefined}
								className={cn(onRowClick && "cursor-pointer")}
								onClick={() => onRowClick?.(row.original)}
								onKeyDown={(event) => {
									if (
										onRowClick &&
										(event.key === "Enter" || event.key === " ")
									) {
										event.preventDefault();
										onRowClick(row.original);
									}
								}}
							>
								{row.getAllCells().map((cell) => (
									<TableCell key={cell.id}>
										<table.FlexRender cell={cell} />
									</TableCell>
								))}
							</TableRow>
						))
					)}
				</TableBody>
			</Table>
		</div>
	);
}
