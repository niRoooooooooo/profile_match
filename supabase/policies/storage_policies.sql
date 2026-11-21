
-- Storage paths follow:
-- user_id/invention_id/filename

CREATE POLICY "Upload own invention files"
ON storage.objects
FOR INSERT TO authenticated
WITH CHECK (
    bucket_id = 'invention-documents'
    AND (storage.foldername(name))[1] =
        (SELECT auth.uid())::text
    AND EXISTS (
        SELECT 1
        FROM public.inventions i
        WHERE i.id::text = (storage.foldername(name))[2]
          AND i.owner_id = (SELECT auth.uid())
    )
);

CREATE POLICY "Read own invention files"
ON storage.objects
FOR SELECT TO authenticated
USING (
    bucket_id = 'invention-documents'
    AND (storage.foldername(name))[1] =
        (SELECT auth.uid())::text
    AND EXISTS (
        SELECT 1
        FROM public.inventions i
        WHERE i.id::text = (storage.foldername(name))[2]
          AND i.owner_id = (SELECT auth.uid())
    )
);
