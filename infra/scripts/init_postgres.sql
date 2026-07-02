-- ════════════════════════════════════════════════════════════════
-- PostgreSQL 初始化脚本
-- 由 postgres 镜像自动执行（仅首次创建数据库时）
-- 全部用 IF NOT EXISTS 保证幂等
-- ════════════════════════════════════════════════════════════════

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- 模糊匹配（导师同名消歧用）

-- ───── 用户 ─────
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    email         VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(32) NOT NULL DEFAULT 'user',   -- admin / user
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- ───── 导师实体（合并后）─────
CREATE TABLE IF NOT EXISTS mentors (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(64) NOT NULL,
    gender          VARCHAR(8),                       -- 男 / 女
    birth_year      INT,
    primary_college VARCHAR(128),                     -- 主学院（职级最高）
    wiki_entry_id   BIGINT,                           -- → wiki_entries.id
    raw_md_paths    TEXT[],                           -- 所有来源 md 路径
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- 同名+同年视为同人（表达式唯一约束需用索引实现，不能用 UNIQUE(...)）
CREATE UNIQUE INDEX IF NOT EXISTS idx_mentors_unique ON mentors(name, COALESCE(birth_year, -1));
CREATE INDEX IF NOT EXISTS idx_mentors_name ON mentors(name);
CREATE INDEX IF NOT EXISTS idx_mentors_name_trgm ON mentors USING gin (name gin_trgm_ops);

-- ───── 导师身份（一对多）─────
CREATE TABLE IF NOT EXISTS mentor_identities (
    id               BIGSERIAL PRIMARY KEY,
    mentor_id        BIGINT NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
    college          VARCHAR(128),                   -- 学院
    subject_direction VARCHAR(128),                  -- 学科方向（如数字经济导师）
    title            VARCHAR(128),                    -- 职称（教授/博导/硕导）
    source_doc_id    BIGINT,                         -- → documents.id
    raw_md_path      TEXT,                           -- 原始 md 路径
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mentor_identities_mentor ON mentor_identities(mentor_id);
CREATE INDEX IF NOT EXISTS idx_mentor_identities_college ON mentor_identities(college);

-- ───── 文档登记 ─────
CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    file_path     TEXT NOT NULL UNIQUE,               -- 相对 /data/output 的路径
    file_type     VARCHAR(16) NOT NULL,               -- pdf / docx / md / ...
    category      VARCHAR(64),                        -- 导师信息/培养工作/招生工作/研工工作/研究生文件
    college       VARCHAR(128),
    subject       VARCHAR(128),
    doc_source    VARCHAR(32) NOT NULL,               -- web_md / attachment
    source_url    TEXT,
    attachment_urls TEXT[],                            -- 附件 URL（来自 md 元数据）
    published_at  TIMESTAMPTZ,                        -- 发布时间
    crawled_at    TIMESTAMPTZ,                        -- 爬取时间
    raw_hash      VARCHAR(64),                        -- 文件 sha256
    md_path       TEXT,                                -- 解析后的 md 路径（若有）
    status        VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending/parsed/embedded/failed
    error_msg     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS idx_documents_doc_source ON documents(doc_source);

-- ───── 切片元数据（正文在 Milvus，这里仅存引用）─────
CREATE TABLE IF NOT EXISTS chunks (
    id            BIGSERIAL PRIMARY KEY,
    document_id   BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index   INT NOT NULL,
    text_preview  VARCHAR(200),                       -- 前 200 字预览
    token_count   INT,
    milvus_id     BIGINT,                             -- Milvus chunks collection 中的主键
    mentor_id     BIGINT REFERENCES mentors(id),      -- 若属于导师信息，关联到 mentor
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_mentor ON chunks(mentor_id);
CREATE INDEX IF NOT EXISTS idx_chunks_milvus ON chunks(milvus_id);

-- ───── Wiki 条目 ─────
CREATE TABLE IF NOT EXISTS wiki_entries (
    id             BIGSERIAL PRIMARY KEY,
    title          VARCHAR(255) NOT NULL UNIQUE,      -- 标题（如「杨玉文」）
    entry_type     VARCHAR(32) NOT NULL,                -- person / policy / process
    content_md     TEXT NOT NULL,                       -- markdown 正文
    content_summary VARCHAR(500),                      -- 摘要（送入 Milvus wiki 集合）
    source_doc_ids BIGINT[],                            -- 来源 document_id 列表
    mention_count  INT NOT NULL DEFAULT 0,              -- 命中次数（沉淀触发计数）
    version        INT NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wiki_entries_type ON wiki_entries(entry_type);
CREATE INDEX IF NOT EXISTS idx_wiki_entries_title_trgm ON wiki_entries USING gin (title gin_trgm_ops);

-- wiki_entries 增加 category/college/subject 字段（幂等，用于 bwiki 风格分类导航）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='wiki_entries' AND column_name='category') THEN
    ALTER TABLE wiki_entries ADD COLUMN category VARCHAR(64);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='wiki_entries' AND column_name='college') THEN
    ALTER TABLE wiki_entries ADD COLUMN college VARCHAR(128);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='wiki_entries' AND column_name='subject') THEN
    ALTER TABLE wiki_entries ADD COLUMN subject VARCHAR(128);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_wiki_entries_college ON wiki_entries(college);
CREATE INDEX IF NOT EXISTS idx_wiki_entries_category ON wiki_entries(category);

-- ───── Wiki 双向链接 ─────
CREATE TABLE IF NOT EXISTS wiki_links (
    id            BIGSERIAL PRIMARY KEY,
    src_entry_id BIGINT NOT NULL REFERENCES wiki_entries(id) ON DELETE CASCADE,
    dst_entry_id BIGINT NOT NULL REFERENCES wiki_entries(id) ON DELETE CASCADE,
    relation      VARCHAR(64),                         -- 例如：advises / related_to
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(src_entry_id, dst_entry_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_wiki_links_src ON wiki_links(src_entry_id);
CREATE INDEX IF NOT EXISTS idx_wiki_links_dst ON wiki_links(dst_entry_id);

-- ───── 会话 ─────
CREATE TABLE IF NOT EXISTS conversations (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);

-- ───── 消息 ─────
CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL,              -- user / assistant / system
    content         TEXT NOT NULL,
    trace           JSONB,                             -- {retrieved, wiki_used, intent, ...}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

-- ───── 触发器：updated_at 自动更新 ─────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN SELECT c.table_name
             FROM information_schema.columns c
             JOIN information_schema.tables t2
                  ON c.table_name = t2.table_name AND c.table_schema = t2.table_schema
             WHERE c.table_schema = 'public'
               AND t2.table_type = 'BASE TABLE'
               AND c.column_name = 'updated_at'
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated ON %I;', t, t);
        EXECUTE format('CREATE TRIGGER trg_%I_updated BEFORE UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION update_updated_at();', t, t);
    END LOOP;
END $$;
