import pytest
import json
from .test_utils import call_job_chat_service, make_service_input, print_response_details


def test_basic_input():
    print("==================TEST==================")
    print("Description: Basic input test. Check if the service can handle a simple input and generate a response.")
    history = []
    content = "I want to add a step to also update the parent record after creating the line items in this job?"
    context = {
        "expression": '''each(
  dataPath('data[*]'),
  combine(
    create(
      'transaction__c',
      fields(
        field('Transaction_Date__c', dataValue('today')),
        relationship(
          'Person_Responsible__r',
          'Staff_ID_Code__c',
          dataValue('person_code')
        ),
        field('metainstanceid__c', dataValue('*meta-instance-id*'))
      )
    ),
    each(
      merge(
        dataPath('line_items[*]'),
        fields(
          field('end', dataValue('time_end')),
          field('parentId', lastReferenceValue('id'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      )
    )
  )
);'''
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta)
    response = call_job_chat_service(service_input)
    print_response_details(response, "basic_input", content=content)
    assert response is not None
    assert "response" in response
    assert isinstance(response["response"], dict)
    assert "response" in response["response"]
    assert "suggested_code" in response["response"] 