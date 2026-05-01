# 13. Export And Import A Copy

Goal: prove the protocol can be shared without overwriting the source protocol.

## Do This

1. Open the published protocol.
2. Use the protocol package export action.
3. Save the JSON or YAML package.
4. Import the package.
5. When Octopus warns that the protocol already exists, choose import as a copy.
6. Publish the copied protocol only after reviewing the imported draft.
7. Run the copy if you need to prove the imported package behaves the same.

## You Are Done When

- The original protocol still exists unchanged.
- The imported copy has an appended or otherwise distinct name.
- The imported copy contains the same stage flow, assignments, declared
  artifacts, skills, and run inputs.
- Skill application remains idempotent.

## Notes

Do not use export-all for this example. Exporting one protocol at a time is
clearer for a user, easier to review, and safer when the goal is to share a
specific workflow.

Previous: [Validate Narrow Artifact](12-validate-narrow-artifact.md).
