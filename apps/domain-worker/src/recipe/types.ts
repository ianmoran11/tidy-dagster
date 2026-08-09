/* Ported from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb; MIT, Copyright (c) 2026 Ian Moran. */
import { z } from "zod";
import {
  cellPredicateSchema,
  cellSelectorSchema,
  dataTypeSchema,
  fillDirectionSchema,
  headerDirectionSchema,
  headerSpecSchema,
  recipeOptionsSchema,
  recipeV01Schema,
  tableSpecSchema,
  valuesSpecSchema,
} from "./schema.js";

export type DataType = z.infer<typeof dataTypeSchema>;
export type HeaderDirection = z.infer<typeof headerDirectionSchema>;
export type FillDirection = z.infer<typeof fillDirectionSchema>;
export type CellPredicate = z.infer<typeof cellPredicateSchema>;
export type CellSelector = z.infer<typeof cellSelectorSchema>;
export type RecipeOptions = z.infer<typeof recipeOptionsSchema>;
export type ValuesSpec = z.infer<typeof valuesSpecSchema>;
export type HeaderSpec = z.infer<typeof headerSpecSchema>;
export type TableSpec = z.infer<typeof tableSpecSchema>;
export type RecipeV01 = z.infer<typeof recipeV01Schema>;
