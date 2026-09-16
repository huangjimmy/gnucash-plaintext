;; A report of one's own whose renderer hands back an empty string.
;;
;; GnuCash takes a string from a renderer as the finished page, on 3.4 as on
;; 5.10 (`gnc:report-render-html` asks `string?` first), so an empty one is an
;; empty page and no error. A first attempt can end there: a renderer that
;; builds its text in a `let` and returns the wrong binding, or returns before
;; adding anything.
;;
;; Printing it would write a page with nothing on it and report success, so
;; `print-invoice` refuses it and says GnuCash drew nothing.

(define (a-report-that-draws-nothing-renderer report-obj)
  "")

(gnc:define-report
  'version 1
  'name "A Report That Draws Nothing"
  'report-guid "a0a1a0a1a0a1a0a1a0a1a0a1a0a1a0a1"
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
  'renderer a-report-that-draws-nothing-renderer)
