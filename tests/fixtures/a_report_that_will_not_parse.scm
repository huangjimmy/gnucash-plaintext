;; A report file with a syntax error in it — the likeliest first-run mistake.
;;
;; Scheme is parentheses, and one too few is what a first `.scm` most often
;; has. `(load …)` then raises, and this tool used to answer "GnuCash could
;; not render the page: (misc-error …)", pointing the reader at the
;; invoice they asked for rather than at the file they wrote.
;;
;; The closing paren of `gnc:define-report` is missing, deliberately.

(define (a-report-that-will-not-parse-renderer report-obj)
  (gnc:make-html-document))

(gnc:define-report
  'version 1
  'name "A Report That Will Not Parse"
  'report-guid "badbadbadbadbadbadbadbadbadbadba"
  'options-generator (lambda () (gnc:new-options))
  'renderer a-report-that-will-not-parse-renderer
