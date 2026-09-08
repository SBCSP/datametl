// Database engine metadata for connection create/edit and badges.
//
// Engine ids must match backend `for_engine` / ConnectionCreate Literal:
//   postgres | mysql | mssql

import type { Engine } from "@/lib/types";

export type { Engine };

export interface EngineMeta {
  value: Engine;
  label: string;
  shortLabel: string;
  description: string;
  defaultPort: number;
  defaultUser: string;
  databasePlaceholder: string;
  hostHint: string;
  sslHint: string;
}

export const ENGINES: EngineMeta[] = [
  {
    value: "postgres",
    label: "PostgreSQL",
    shortLabel: "Postgres",
    description: "Postgres, Supabase, RDS Postgres, Neon, and compatible servers.",
    defaultPort: 5432,
    defaultUser: "postgres",
    databasePlaceholder: "postgres",
    hostHint: "For Supabase, use the pooler host on port 6543 or direct on 5432.",
    sslHint:
      "AWS RDS: use verify-full with the global root CA bundle. Supabase works with require.",
  },
  {
    value: "mysql",
    label: "MySQL",
    shortLabel: "MySQL",
    description: "MySQL 8+, Amazon Aurora MySQL, and MariaDB-compatible servers.",
    defaultPort: 3306,
    defaultUser: "root",
    databasePlaceholder: "mysql",
    hostHint: "Use the writer endpoint for Aurora; port is usually 3306.",
    sslHint:
      "Managed MySQL (RDS/Aurora): use verify-ca or require with the provider CA bundle.",
  },
  {
    value: "mssql",
    label: "SQL Server",
    shortLabel: "SQL Server",
    description: "Microsoft SQL Server, Azure SQL Database, and compatible TDS servers.",
    defaultPort: 1433,
    defaultUser: "sa",
    databasePlaceholder: "master",
    hostHint:
      "Default port 1433. From the DataMETL containers use the compose service hostname (e.g. engine-mssql).",
    sslHint:
      "Azure SQL usually requires encryption. The pymssql/FreeTDS driver has limited TLS knobs — prefer VPN/private link for on-prem, and test carefully against Azure.",
  },
];

export function engineMeta(engine: string | null | undefined): EngineMeta | null {
  return ENGINES.find((e) => e.value === engine) ?? null;
}

export function engineLabel(engine: string | null | undefined): string {
  return engineMeta(engine)?.label ?? engine ?? "Unknown";
}
