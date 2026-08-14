;; A `.scm` with two reports in it, one of which forgot its `'name`.
;;
;; `gnc:define-report` refuses a definition with no `report-guid` and accepts
;; one with no `'name`, so the first of these registers a template whose name
;; field is `#f`. That is a plausible first attempt from the reader
;; `--report-file` is for.
;;
;; What it costs is not local to that report. A name lookup walks *every*
;; registered template, so one nameless template made `(string=? #f "…")`
;; raise for any `--report <name>` afterwards in the same process — the reader
;; asks for `Fancy Invoice` and is told
;; "GnuCash could not render the document: (wrong-type-arg …)", about a
;; mistake in a file of theirs somewhere else entirely.
;;
;; The second report is here because the nameless one cannot be drawn at all:
;; measured on GnuCash 5.10, rendering it fails inside GnuCash's own
;; `SWIG_Guile_scm2newstr` on the `#f` name, which is GnuCash's answer to its
;; own definition and not something this tool can improve. So the fixture
;; carries a working report to ask for by name, and asking for it walks past
;; the nameless one — which is the regression.

(define (a-report-that-did-name-itself-renderer report-obj)
  (let ((document (gnc:make-html-document)))
    (gnc:html-document-set-title! document "A Report That Did Name Itself")
    (gnc:html-document-add-object!
      document
      (gnc:make-html-text
        (gnc:html-markup-p "A REPORT THAT DID NAME ITSELF")))
    document))

;; The document arrives through `General / Invoice Number`, so a report that
;; is going to be drawn has to declare it — both ways GnuCash has had, for the
;; reason `a_report_of_your_own.scm` explains. Without it the legacy option
;; API looks the name up, gets `#f`, and fails in `vector-ref`.
(define (an-invoice-option-db)
  (if (defined? 'gnc-new-optiondb)
      (let ((options (gnc-new-optiondb)))
        (gnc-register-invoice-option options
                                     "General" "Invoice Number" "x" "" '())
        options)
      (let ((options (gnc:new-options)))
        (gnc:register-option
          options
          (gnc:make-invoice-option "General" "Invoice Number" "x" ""
                                   (lambda () '()) #f))
        options)))

(gnc:define-report
  'version 1
  'report-guid "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"
  'options-generator an-invoice-option-db
  'renderer (lambda (report-obj) (gnc:make-html-document)))

(gnc:define-report
  'version 1
  'name "A Report That Did Name Itself"
  'report-guid "0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e"
  'options-generator an-invoice-option-db
  'renderer a-report-that-did-name-itself-renderer)
