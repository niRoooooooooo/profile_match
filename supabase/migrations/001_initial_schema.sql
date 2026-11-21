
-- 1. Innovator accounts and roles

CREATE TABLE public.user_profiles (
    id UUID PRIMARY KEY
        REFERENCES auth.users(id)
        ON DELETE CASCADE,

    full_name TEXT NOT NULL,
    department TEXT,

    role TEXT NOT NULL DEFAULT 'innovator'
        CHECK (role IN (
            'innovator',
            'innovation_center',
            'industry_liaison',
            'management',
            'administrator',
            'partner'
        )),

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Registered inventions

CREATE TABLE public.inventions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    owner_id UUID NOT NULL
        REFERENCES public.user_profiles(id),

    title TEXT NOT NULL,
    abstract TEXT,
    domain TEXT,
    trl SMALLINT CHECK (trl BETWEEN 1 AND 9),
    ip_status TEXT,
    inventors TEXT[] DEFAULT '{}',
    keywords TEXT[] DEFAULT '{}',

    confidentiality TEXT NOT NULL DEFAULT 'restricted'
        CHECK (confidentiality IN (
            'public',
            'restricted',
            'confidential'
        )),

    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN (
            'draft',
            'processing',
            'awaiting_review',
            'approved'
        )),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Uploaded invention documents

CREATE TABLE public.invention_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    invention_id UUID NOT NULL
        REFERENCES public.inventions(id)
        ON DELETE CASCADE,

    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL UNIQUE,
    mime_type TEXT,
    file_size BIGINT,

    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. One editable approved profile per invention

CREATE TABLE public.invention_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    invention_id UUID NOT NULL UNIQUE
        REFERENCES public.inventions(id)
        ON DELETE CASCADE,

    ai_extracted_data JSONB NOT NULL,
    approved_data JSONB NOT NULL,

    approved_by UUID NOT NULL
        REFERENCES public.user_profiles(id),

    revision INTEGER NOT NULL DEFAULT 1
        CHECK (revision >= 1),

    approved_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Automatically update modification timestamps

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER inventions_updated_at
BEFORE UPDATE ON public.inventions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER invention_profiles_updated_at
BEFORE UPDATE ON public.invention_profiles
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

-- Enable row-level security

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invention_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invention_profiles ENABLE ROW LEVEL SECURITY;

-- Innovators can view only their own account profile.

CREATE POLICY "Read own user profile"
ON public.user_profiles
FOR SELECT TO authenticated
USING ((SELECT auth.uid()) = id);

-- Invention ownership

CREATE POLICY "Read own inventions"
ON public.inventions
FOR SELECT TO authenticated
USING ((SELECT auth.uid()) = owner_id);

CREATE POLICY "Create own inventions"
ON public.inventions
FOR INSERT TO authenticated
WITH CHECK ((SELECT auth.uid()) = owner_id);

CREATE POLICY "Update own inventions"
ON public.inventions
FOR UPDATE TO authenticated
USING ((SELECT auth.uid()) = owner_id)
WITH CHECK ((SELECT auth.uid()) = owner_id);

-- Documents must belong to an invention owned by the user.

CREATE POLICY "Read own documents"
ON public.invention_documents
FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.inventions i
        WHERE i.id = invention_id
          AND i.owner_id = (SELECT auth.uid())
    )
);

CREATE POLICY "Add own documents"
ON public.invention_documents
FOR INSERT TO authenticated
WITH CHECK (
    EXISTS (
        SELECT 1 FROM public.inventions i
        WHERE i.id = invention_id
          AND i.owner_id = (SELECT auth.uid())
    )
);

-- Access to approved profiles

CREATE POLICY "Read own invention profiles"
ON public.invention_profiles
FOR SELECT TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.inventions i
        WHERE i.id = invention_id
          AND i.owner_id = (SELECT auth.uid())
    )
);

CREATE POLICY "Create own invention profiles"
ON public.invention_profiles
FOR INSERT TO authenticated
WITH CHECK (
    approved_by = (SELECT auth.uid())
    AND EXISTS (
        SELECT 1 FROM public.inventions i
        WHERE i.id = invention_id
          AND i.owner_id = (SELECT auth.uid())
    )
);

CREATE POLICY "Update own invention profiles"
ON public.invention_profiles
FOR UPDATE TO authenticated
USING (
    EXISTS (
        SELECT 1 FROM public.inventions i
        WHERE i.id = invention_id
          AND i.owner_id = (SELECT auth.uid())
    )
)
WITH CHECK (
    approved_by = (SELECT auth.uid())
    AND EXISTS (
        SELECT 1 FROM public.inventions i
        WHERE i.id = invention_id
          AND i.owner_id = (SELECT auth.uid())
    )
);
