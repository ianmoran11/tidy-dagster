import {
  buildHeaderDirectionGroups,
  resolveRelationshipAttachmentAtAddress,
} from "./relationshipResolution.js";
import type { RecipeV01 } from "../recipe/types.js";
import type { ResolvedRecipeSelectors } from "../recipe/resolveSelectors.js";

export function buildGeometryEvidence(
  recipe: RecipeV01,
  resolved: ResolvedRecipeSelectors,
) {
  return {
    sheet: resolved.sheet,
    tables: recipe.tables.map((table, tableIndex) => {
      const selectors = resolved.tables[tableIndex];
      return {
        table: table.name,
        headers: table.headers.map((header, headerIndex) => {
          const headerAddresses =
            selectors.headers[headerIndex].result.addresses;
          const groups = buildHeaderDirectionGroups({
            headerAddresses,
            valueAddresses: selectors.values.addresses,
            direction: header.direction,
            fill: header.fill,
            directionOverrides: header.direction_overrides,
          });
          return {
            name: header.name,
            defaultDirection: header.direction,
            anchors: groups.flatMap((group) =>
              group.candidates.map((candidate) => ({
                address: candidate.address,
                effectiveDirection: group.direction,
                spanEndRow: candidate.spanEndRow,
                spanEndCol: candidate.spanEndCol,
              })),
            ),
            values: selectors.values.addresses.map((address) => ({
              address,
              ...resolveRelationshipAttachmentAtAddress(groups, address),
            })),
          };
        }),
      };
    }),
  };
}
