import DOMPurify from "dompurify";

const SANITIZE_OPTIONS = {
	FORBID_ATTR: ["style"],
	FORBID_TAGS: [
		"base",
		"embed",
		"iframe",
		"link",
		"meta",
		"object",
		"script",
		"style",
	],
};

/** Sanitize model, notebook, and Markdown output before binding it with v-html. */
export function sanitizeHtml(content: string): string {
	return DOMPurify.sanitize(content, SANITIZE_OPTIONS);
}
