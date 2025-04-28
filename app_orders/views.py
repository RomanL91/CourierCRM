from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework import status
from .serializers import DeliveryProofCreateSerializer
from django.http import HttpResponse
from rest_framework.parsers import MultiPartParser, FormParser


class DeliveryProofUploadView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, format=None):
        serializer = DeliveryProofCreateSerializer(data=request.data)
        if serializer.is_valid():
            delivery_proof = serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            print("Ошибки валидации:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request, format=None):
        return HttpResponse("Пшел вон отседова!", status=status.HTTP_400_BAD_REQUEST)
