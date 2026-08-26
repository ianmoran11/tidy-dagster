declare module "exceljs/lib/xlsx/xform/style/styles-xform.js" {
  export default class StylesXform {
    parseStream(stream: AsyncIterable<Uint8Array>): Promise<void>;
    getStyleModel(index: number): Record<string, unknown> | undefined;
  }
}

declare module "exceljs/lib/utils/utils.js" {
  const excelUtils: {
    excelToDate(value: number, date1904?: boolean): Date;
    isDateFmt(format?: string): boolean;
  };
  export default excelUtils;
}
