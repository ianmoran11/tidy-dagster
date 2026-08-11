export type CellDataType =
  "blank" | "string" | "numeric" | "boolean" | "date" | "error";

export type HeaderDirection = "N" | "W" | "NNW" | "WNW";
export type FillDirection = "right" | "down";

export type CellPredicate = {
  data_type?: CellDataType[];
  non_blank?: boolean;
  has_formula?: boolean;
  has_comment?: boolean;
  style_id?: string[];
};

/** A canonical R1C1 address or canonical R1C1 range. */
export type CellSelectorEntry = string;

export type CellSelectorObject = {
  range?: string;
  cells?: CellSelectorEntry[];
  where?: CellPredicate;
};

export type CellSelector = string | CellSelectorEntry[] | CellSelectorObject;

export type RecipeOptions = {
  include_blank_values?: boolean;
  preserve_source_address?: boolean;
  preserve_header_source_address?: boolean;
  preserve_formatted_value?: boolean;
  preserve_non_table_cells?: boolean;
  include_blank_non_table_cells?: boolean;
};

export type ValuesSpec = {
  name: string;
  cells: CellSelector;
};

export type HeaderSpec = {
  name: string;
  direction: HeaderDirection;
  direction_overrides?: Record<string, HeaderDirection>;
  cells: CellSelector;
  fill?: FillDirection;
  required?: boolean;
};

export type TableSpec = {
  name: string;
  values: ValuesSpec;
  headers: HeaderSpec[];
  options?: RecipeOptions;
};

export type RecipeV01 = {
  version: "0.1";
  sheet: string;
  tables: TableSpec[];
  options?: RecipeOptions;
};
