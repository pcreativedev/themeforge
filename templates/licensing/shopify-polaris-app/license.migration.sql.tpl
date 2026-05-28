-- pcreative license cache table — append to prisma/schema.prisma
-- model License {
--   shop          String   @id
--   jwt           String
--   lastHeartbeat DateTime @default(now())
--   watermark     String   @default("")
--   updatedAt     DateTime @updatedAt
-- }

-- Then: npx prisma migrate dev --name add_license

CREATE TABLE IF NOT EXISTS "License" (
  "shop" TEXT PRIMARY KEY,
  "jwt" TEXT NOT NULL,
  "lastHeartbeat" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "watermark" TEXT NOT NULL DEFAULT '',
  "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
