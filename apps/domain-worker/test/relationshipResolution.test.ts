/* Source-derived from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
// @vitest-environment node

import { describe, expect, it } from "vitest";
import {
  buildHeaderDirectionGroups,
  resolveRelationshipAttachmentAtAddress,
  resolveRelationshipSelections,
} from "../src/executor/relationshipResolution.js";
import type { HeaderDirection } from "../src/recipe/types.js";

describe("shared relationship resolution", () => {
  it.each([
    ["N", ["R2C2", "R4C2"], ["R3C2", "R5C2"]],
    ["W", ["R3C1", "R3C3"], ["R3C2", "R3C4"]],
    ["NNW", ["R2C2", "R2C4"], ["R3C2", "R3C3", "R3C4"]],
    ["WNW", ["R2C1", "R4C1"], ["R2C2", "R3C2", "R4C2"]],
  ] as const)(
    "keeps indexed batch selection equivalent to executor selection for %s",
    (direction, headers, values) => {
      const groups = buildHeaderDirectionGroups({
        headerAddresses: headers,
        valueAddresses: values,
        direction,
      });
      const batch = resolveRelationshipSelections(groups, values);
      for (const value of values) {
        expect(batch.get(value)?.selectedAddress).toBe(
          resolveRelationshipAttachmentAtAddress(groups, value).selectedAddress,
        );
      }
    },
  );

  it("preserves sparse cascading scope across blank bands and fill-adjacent anchors", () => {
    const values = ["R3C2", "R9C3", "R12C4"];
    const groups = buildHeaderDirectionGroups({
      headerAddresses: ["R2C2", "R2C4"],
      valueAddresses: values,
      direction: "NNW",
    });
    expect(
      values.map(
        (value) =>
          resolveRelationshipAttachmentAtAddress(groups, value).selectedAddress,
      ),
    ).toEqual(["R2C2", "R2C2", "R2C4"]);
  });

  it("treats merged-master and merged-child addresses as ordinary selected anchors", () => {
    const groups = buildHeaderDirectionGroups({
      headerAddresses: ["R2C2", "R2C3"],
      valueAddresses: ["R3C2", "R3C3"],
      direction: "N",
    });
    expect(
      resolveRelationshipSelections(groups, ["R3C2", "R3C3"]),
    ).toMatchObject(
      new Map([
        ["R3C2", { selectedAddress: "R2C2" }],
        ["R3C3", { selectedAddress: "R2C3" }],
      ]),
    );
  });

  it("preserves mixed override groups and distance arbitration", () => {
    const values = ["R5C5"];
    const groups = buildHeaderDirectionGroups({
      headerAddresses: ["R2C5", "R5C3"],
      valueAddresses: values,
      direction: "N",
      directionOverrides: { R5C3: "W" },
    });
    const attachment = resolveRelationshipAttachmentAtAddress(
      groups,
      values[0],
    );
    expect(attachment).toMatchObject({
      selectedAddress: "R5C3",
      direction: "W",
      candidates: ["R5C3", "R2C5"],
    });
  });

  it("uses lexicographic cascading precedence beyond one million rows", () => {
    const direction: HeaderDirection = "WNW";
    const groups = buildHeaderDirectionGroups({
      headerAddresses: ["R1048576C2", "R1C3"],
      valueAddresses: ["R1048576C4"],
      direction,
    });
    expect(
      resolveRelationshipAttachmentAtAddress(groups, "R1048576C4")
        .selectedAddress,
    ).toBe("R1C3");
  });
});
