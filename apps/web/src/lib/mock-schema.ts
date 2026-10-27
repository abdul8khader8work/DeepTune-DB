export type SchemaColumn = {
  name: string;
  type: string;
  pk?: boolean;
  indexed?: boolean;
};

export type SchemaTable = {
  name: string;
  columns: SchemaColumn[];
};

export const schema: SchemaTable[] = [
  {
    name: "orders",
    columns: [
      { name: "id", type: "int4", pk: true },
      { name: "customer_id", type: "int4", indexed: true },
      { name: "order_date", type: "timestamp", indexed: true },
      { name: "status", type: "text" },
      { name: "total", type: "numeric" },
    ],
  },
  {
    name: "customers",
    columns: [
      { name: "id", type: "int4", pk: true },
      { name: "name", type: "text" },
      { name: "region_id", type: "int4", indexed: true },
    ],
  },
  {
    name: "regions",
    columns: [
      { name: "id", type: "int4", pk: true },
      { name: "name", type: "text" },
    ],
  },
];

export const initiallyOpen: Record<string, boolean> = {
  orders: true,
  customers: true,
  regions: false,
};
