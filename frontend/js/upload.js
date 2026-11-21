
/*
========================================
PROFILE MATCH — DOCUMENT UPLOAD SERVICE
Phase 3: Supabase Storage Integration
========================================
*/

// Actual Supabase Storage bucket ID
const DOCUMENT_BUCKET = "invention-document";

// Upload limits
const MAX_FILE_SIZE = 20 * 1024 * 1024;
const MAX_FILES = 5;

// Supported document formats
const ALLOWED_FILES = {
    pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    doc: "application/msword"
};


// ========================================
// 1. VALIDATE DOCUMENTS
// ========================================

window.validateInventionFiles = function (files) {

    if (!files || files.length === 0) {
        throw new Error(
            "Please select at least one document."
        );
    }

    if (files.length > MAX_FILES) {
        throw new Error(
            `You can upload a maximum of ${MAX_FILES} files at once.`
        );
    }

    for (const file of files) {

        const extension = file.name
            .split(".")
            .pop()
            .toLowerCase();

        if (!ALLOWED_FILES[extension]) {
            throw new Error(
                `${file.name}: Unsupported file format. ` +
                "Only PDF, DOCX, and DOC are allowed."
            );
        }

        if (file.size === 0) {
            throw new Error(
                `${file.name}: The file is empty.`
            );
        }

        if (file.size > MAX_FILE_SIZE) {
            throw new Error(
                `${file.name}: File exceeds 20 MB.`
            );
        }
    }

    return true;
};


// ========================================
// 2. UPLOAD DOCUMENTS TO SUPABASE
// ========================================

window.uploadInventionFiles = async function ({
    client,
    userId,
    inventionId,
    files,
    onProgress
}) {

    // Validate before uploading
    window.validateInventionFiles(files);

    if (!client || !userId || !inventionId) {
        throw new Error(
            "Missing authentication or invention information."
        );
    }

    const uploaded = [];
    const failed = [];

    for (let i = 0; i < files.length; i++) {

        const file = files[i];

        if (onProgress) {
            onProgress(
                `Uploading document ${i + 1} of ${files.length}: ${file.name}`
            );
        }

        const extension = file.name
            .split(".")
            .pop()
            .toLowerCase();

        const mimeType = ALLOWED_FILES[extension];

        /*
        Storage folder structure:

        invention-document/
            user-id/
                invention-id/
                    random-file-id.pdf
        */

        const uniqueFileName =
            `${crypto.randomUUID()}.${extension}`;

        const storagePath =
            `${userId}/${inventionId}/${uniqueFileName}`;

        let objectUploaded = false;

        try {

            // --------------------------------
            // A. UPLOAD FILE TO SUPABASE STORAGE
            // --------------------------------

            const { data: storageData, error: uploadError } =
                await client.storage
                    .from(DOCUMENT_BUCKET)
                    .upload(
                        storagePath,
                        file,
                        {
                            contentType: mimeType,
                            cacheControl: "120",
                            upsert: false
                        }
                    );

            if (uploadError) {
                throw new Error(
                    `Storage upload failed: ${uploadError.message}`
                );
            }

            objectUploaded = true;

            console.log(
                "File uploaded to Supabase:",
                storageData?.path || storagePath
            );


            // --------------------------------
            // B. SAVE FILE METADATA TO DATABASE
            // --------------------------------

            const documentRecord = {
                invention_id: inventionId,
                original_filename: file.name,
                storage_path: storagePath,
                mime_type: mimeType,
                file_size: file.size
            };

            const { error: metadataError } =
                await client
                    .from("invention_documents")
                    .insert(documentRecord);

            if (metadataError) {
                throw new Error(
                    `Database metadata failed: ${metadataError.message}`
                );
            }

            // --------------------------------
            // C. RECORD SUCCESS
            // --------------------------------

            uploaded.push(file.name);

            console.log(
                "Document metadata saved:",
                file.name
            );

        } catch (error) {

            console.error(
                `Upload failed for ${file.name}:`,
                error
            );

            /*
            If the file reached Storage but its
            database record failed, try deleting
            the uploaded file to avoid an orphan.
            */

            if (objectUploaded) {

                const { error: cleanupError } =
                    await client.storage
                        .from(DOCUMENT_BUCKET)
                        .remove([storagePath]);

                if (cleanupError) {
                    console.error(
                        "Storage cleanup failed:",
                        cleanupError.message
                    );
                }
            }

            failed.push({
                filename: file.name,
                reason: error.message
            });
        }
    }


    // ========================================
    // 3. RETURN UPLOAD RESULTS
    // ========================================

    if (onProgress) {

        if (failed.length === 0) {

            onProgress(
                `${uploaded.length} document(s) uploaded successfully.`
            );

        } else {

            onProgress(
                `${uploaded.length} uploaded, ` +
                `${failed.length} failed.`
            );
        }
    }

    return {
        uploaded,
        failed
    };
};
