;; A report of one's own that keeps the block but not the table inside it.
;;
;; README says to start from `invoice.scm`, and a reader who does keeps
;; `(gnc:make-html-div/markup "company-table" …)` — but nothing obliges them
;; to keep a *table* in it. Putting the seller's details in as text and laying
;; the line items out below in a table is an ordinary thing to do to a page.
;;
;; What that used to cost: the row goes in at the first `</tbody>` after the
;; anchor, and with no table in the block that is the line items' one. The
;; seller's GST and PST numbers were inserted as a row **among the invoice
;; line items** — no refusal, because the anchor was found, and no warning
;; either, for the same reason. A Canadian invoice, exit 0, nothing on stderr.
;;
;; The block is found by its own `</div>` now, and a `</tbody>` outside it is
;; not a place to put anything.

(define (a-report-with-a-textual-block-renderer report-obj)
  (let* ((document (gnc:make-html-document))
         (options (gnc:report-options report-obj))
         (invoice (gnc:option-value
                    (gnc:lookup-option options "General" "Invoice Number")))
         (seller (gnc:make-html-text
                   (gnc:html-markup-p "MY COMPANY, WRITTEN OUT AS TEXT")))
         (entries (gnc:make-html-table)))
    (gnc:html-document-set-title! document "A Report With A Textual Block")
    ;; The block, with no table in it.
    (gnc:html-document-add-object!
      document (gnc:make-html-div/markup "company-table" seller))
    ;; And a table below it that is nothing to do with the seller.
    (gnc:html-table-append-row! entries (list "THE LINE ITEMS TABLE"))
    (gnc:html-table-append-row!
      entries
      (list (string-append "document: "
                           (if (and invoice (not (null? invoice)))
                               (gncInvoiceGetID invoice)
                               "none"))))
    (gnc:html-document-add-object! document entries)
    document))

(gnc:define-report
  'version 1
  'name "A Report With A Textual Block"
  'report-guid "7ab17ab17ab17ab17ab17ab17ab17ab1"
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
  'renderer a-report-with-a-textual-block-renderer)
