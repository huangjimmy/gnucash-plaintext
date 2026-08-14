;; A report of one's own that kept GnuCash's page furniture.
;;
;; This is the shape README's step 4 sends people to: "Start from
;; `invoice.scm`". A reader who does that changes the layout and keeps the
;; helpers, so their page still carries the two blocks GnuCash's own writes —
;; `gnc:make-html-div/markup "company-table"` and `"client-table"`, each
;; wrapping a table, which is exactly how `invoice.scm` emits them.
;;
;; So the registration numbers and the `extra_text` lines still go in, and
;; README says so. That is the branch of `_with_extra_row` where the block is
;; found and `required` is false — a page this project has no claim on, that
;; nonetheless has somewhere to put what the book carries.
;;
;; Every other `.scm` here draws a bare paragraph and has neither block, so
;; each of them exercises the *other* half: nothing to splice into, nothing
;; refused. Without this one, making `ours = False` skip the splice outright
;; would look like a tidy simplification, leave the suite green, and print a
;; Canadian book's invoice with no GST number and no warning.

(define (a-report-from-invoice-scm-renderer report-obj)
  (let* ((document (gnc:make-html-document))
         (options (gnc:report-options report-obj))
         (invoice (gnc:option-value
                    (gnc:lookup-option options "General" "Invoice Number")))
         (company (gnc:make-html-table))
         (client (gnc:make-html-table)))
    (gnc:html-document-set-title! document "A Report From Invoice Scm")
    (gnc:html-table-append-row! company (list "MY COMPANY BLOCK"))
    (gnc:html-table-append-row! client (list "MY CLIENT BLOCK"))
    (gnc:html-document-add-object!
      document
      (gnc:make-html-text
        (gnc:html-markup-p "A PAGE THAT KEPT GNUCASH'S BLOCKS")
        (gnc:html-markup-p
          (string-append "document: "
                         (if (and invoice (not (null? invoice)))
                             (gncInvoiceGetID invoice)
                             "none")))))
    (gnc:html-document-add-object!
      document (gnc:make-html-div/markup "company-table" company))
    (gnc:html-document-add-object!
      document (gnc:make-html-div/markup "client-table" client))
    document))

(gnc:define-report
  'version 1
  'name "A Report From Invoice Scm"
  'report-guid "c0dec0dec0dec0dec0dec0dec0dec0de"
  'options-generator
    (lambda ()
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
  'renderer a-report-from-invoice-scm-renderer)
