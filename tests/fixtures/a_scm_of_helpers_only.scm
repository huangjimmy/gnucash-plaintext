;; A `.scm` that defines no report at all.
;;
;; `--report-file` is only constrained to be accompanied by `--report`, and
;; loading a file of shared helpers beside one of GnuCash's own reports is a
;; legitimate use of it — a stylesheet tweak, a define a person's other
;; reports use.
;;
;; It matters because "this file registered nothing" is also the symptom of
;; the duplicate-guid mistake, and the sentence written for that one blames a
;; guid. Attached to any failure, it would blame this file's guid — which it
;; does not have — for whatever went wrong somewhere else.

(define (a-helper-of-mine amount)
  (string-append "<<" (number->string amount) ">>"))
