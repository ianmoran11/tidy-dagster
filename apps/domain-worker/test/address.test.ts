/* Source-derived from TidyCell commit 1be6c995fa931e9860468e40490433161b0121cb (MIT). */
import { describe, expect, it } from "vitest";
import {
  AddressValidationError,
  a1RangeToR1C1,
  a1ToR1C1,
  expandRange,
  formatCell,
  formatRange,
  isAddressValidationError,
  parseA1Cell,
  parseCell,
  parseRange,
} from "../src/address.js";

describe("R1C1 address handling", () => {
  it.each([
    ["R1C1", { row: 1, col: 1 }],
    ["R1C2", { row: 1, col: 2 }],
    ["R2C1", { row: 2, col: 1 }],
    ["R3C4", { row: 3, col: 4 }],
    ["R8C7", { row: 8, col: 7 }],
    ["R12C3", { row: 12, col: 3 }],
    ["R99C100", { row: 99, col: 100 }],
    ["R1048576C16384", { row: 1048576, col: 16384 }],
    [" r5c6 ", { row: 5, col: 6 }],
  ])("parses valid address %s", (input, expected) => {
    expect(parseCell(input)).toEqual(expected);
  });

  it.each([
    [{ row: 1, col: 1 }, "R1C1"],
    [{ row: 3, col: 4 }, "R3C4"],
    [{ row: 1048576, col: 16384 }, "R1048576C16384"],
  ])("formats %o as %s", (input, expected) => {
    expect(formatCell(input)).toBe(expected);
  });

  it("parses and formats ranges", () => {
    expect(parseRange("R3C4:R4C5")).toEqual({
      start: { row: 3, col: 4 },
      end: { row: 4, col: 5 },
    });
    expect(
      formatRange({
        start: { row: 3, col: 4 },
        end: { row: 4, col: 5 },
      }),
    ).toBe("R3C4:R4C5");
  });

  it("expands ranges in row-major order", () => {
    expect(expandRange("R3C4:R4C5")).toEqual(["R3C4", "R3C5", "R4C4", "R4C5"]);
  });

  it("rejects ranges that would expand past the supported cell budget", () => {
    expect(() => expandRange("R1C1:R1048576C16384")).toThrow(
      AddressValidationError,
    );
  });

  it.each([
    "",
    " ",
    "R0C1",
    "R1C0",
    "R-1C1",
    "R1C",
    "RC1",
    "1R1C",
    "R1 C1",
    "A1",
    "R1C1:R2C2",
    "R1048577C1",
    "R1C16385",
    "R9007199254740992C1",
  ])("throws typed validation errors for invalid cell %s", (input) => {
    expect(() => parseCell(input)).toThrow(AddressValidationError);

    try {
      parseCell(input);
      throw new Error("Expected parseCell to fail.");
    } catch (error) {
      expect(isAddressValidationError(error)).toBe(true);
    }
  });

  it.each(["", "R1C1", "R1C1:", ":R2C2", "R2C1:R1C1", "R1C2:R1C1", "A1:B2"])(
    "throws typed validation errors for invalid range %s",
    (input) => {
      expect(() => parseRange(input)).toThrow(AddressValidationError);
    },
  );
});

describe("A1 aliases", () => {
  it.each([
    ["A1", { row: 1, col: 1 }],
    ["D3", { row: 3, col: 4 }],
    ["AA10", { row: 10, col: 27 }],
    ["XFD1048576", { row: 1048576, col: 16384 }],
  ])("parses A1 alias %s", (input, expected) => {
    expect(parseA1Cell(input)).toEqual(expected);
  });

  it("converts A1 cells and ranges to R1C1", () => {
    expect(a1ToR1C1("D3")).toBe("R3C4");
    expect(a1RangeToR1C1("D3:G8")).toBe("R3C4:R8C7");
  });
});
